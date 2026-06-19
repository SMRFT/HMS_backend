from django.http import JsonResponse
from pymongo import MongoClient
import os
import json
import pytz
from datetime import datetime, date
import traceback
from django.utils.dateparse import parse_datetime
from decimal import Decimal, InvalidOperation

from bson import ObjectId
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone
from django.db.models import Max

# Auth/permissions
import os
from pymongo import MongoClient
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from pyauth.auth import HasRoleAndDataPermission, HasRolePermission
from ..models import Patient, SalesReturn


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_salesreturn_details(request):
    try:
        from_date = request.GET.get("from_date")
        to_date   = request.GET.get("to_date")

        qs = SalesReturn.objects.all()

        # ✅ FIX 1: Proper datetime filtering (NO __date)
        if from_date and to_date:
            try:
                from_date = datetime.strptime(from_date, "%Y-%m-%d")
                to_date   = datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)

                qs = qs.filter(
                    return_bill_date__gte=from_date,
                    return_bill_date__lt=to_date,
                )
            except Exception as e:
                return Response({
                    "status": "error",
                    "message": f"Invalid date format: {str(e)}"
                }, status=400)

        records = list(qs.order_by("-return_bill_date"))

        # ✅ DEBUG (remove in production if needed)
        print("SalesReturn records found:", len(records))

        if not records:
            return Response({
                "status": "success",
                "data": [],
                "message": "No records found"
            })

        # ✅ Collect IDs
        uhids = {r.uhid for r in records if r.uhid}
        created_by_ids = {r.created_by for r in records if r.created_by}

        # ✅ Patient Lookup
        patient_map = {}
        patients = Patient.objects.filter(uhid__in=uhids)

        for p in patients:
            name_parts = [p.salutation, p.firstName, p.lastName]
            patient_map[p.uhid] = " ".join([x for x in name_parts if x]).strip()

        # ✅ User Lookup (MongoDB)
        user_map = {}
        try:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            global_db = client["GLOBAL"]

            profiles = global_db["backend_diagnostics_profile"].find(
                {"employeeId": {"$in": list(created_by_ids)}},
                {"employeeId": 1, "employeeName": 1},
            )

            user_map = {
                str(p["employeeId"]): p.get("employeeName", "")
                for p in profiles
            }

            client.close()

        except Exception as e:
            print("MongoDB user lookup failed:", str(e))

        # ✅ Final Response Build
        data = []
        for r in records:
            data.append({
                "return_bill_no":   r.return_bill_no,
                "return_bill_date": r.return_bill_date,
                "bill_no":          r.bill_no,
                "uhid":             r.uhid,
                "return_amount":    r.return_amount,
                "status":           r.status,
                "bill_type":        r.bill_type,
                "mode": "Cash Return" if r.PaymentType == "Cash" else "IP Credit",
                "patient_name":     patient_map.get(r.uhid, ""),
                "pharmacist_name":  user_map.get(str(r.created_by), r.created_by or ""),
            })

        return Response({
            "status": "success",
            "count": len(data),
            "data": data
        })

    except Exception as e:
        print("SalesReturn API Error:", str(e))
        return Response({
            "status": "error",
            "message": str(e)
        }, status=500)


from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from datetime import date
from ..models import Patient


@api_view(["GET"])
def salesreturn_get_patientdetails(request):
    try:
        uhid = request.GET.get("uhid", "").strip()
 
        if not uhid:
            return Response({
                "status": "error",
                "message": "UHID is required"
            }, status=status.HTTP_400_BAD_REQUEST)
 
        # ── FIX #2: partial match — "7878" finds "S025/007878" ──────────────
        # Try exact match first; fall back to substring match
        patient = Patient.objects.filter(uhid=uhid).first()
        if not patient:
            patient = Patient.objects.filter(uhid__icontains=uhid).first()
 
        if not patient:
            return Response({
                "status": "error",
                "message": "Patient not found"
            }, status=status.HTTP_404_NOT_FOUND)
 
        # ── Admission (safe for Djongo) ──────────────────────────────────────
        try:
            from ..models import Admission
            admissions = Admission.objects.filter(
                uhid=patient.uhid
            ).order_by('-admissionDateTime')
 
            active_admission = None
            for adm in admissions:
                if adm.is_admitted:
                    active_admission = adm
                    break
        except Exception:
            active_admission = None
 
        ip_number = active_admission.ipNumber if active_admission else ""
 
        # ── Age calculation ──────────────────────────────────────────────────
        if not patient.dob:
            age_data = {"years": 0, "months": 0, "days": 0}
        else:
            today_date = date.today()
            dob = patient.dob
 
            years  = today_date.year  - dob.year
            months = today_date.month - dob.month
            days   = today_date.day   - dob.day
 
            if days < 0:
                months -= 1
                days += 30
            if months < 0:
                years  -= 1
                months += 12
 
            age_data = {"years": years, "months": months, "days": days}
 
        name = f"{patient.firstName} {patient.lastName}".strip()
 
        return Response({
            "status": "success",
            "data": {
                "uhid":       patient.uhid,
                "ip_number":  ip_number,
                "name":       name,
                "gender":     patient.gender,
                "age":        age_data,
            }
        }, status=status.HTTP_200_OK)
 
    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e) or "Unknown error",
            "error_type": type(e).__name__,
            "trace": traceback.format_exc()
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
 

def _get_db():
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    return client, client["HMS"]
 
 
def _convert_decimal(val):
    return float(val.to_decimal()) if isinstance(val, Decimal128) else val






@api_view(["GET"])
def salesreturn_get_uhid_bills(request):
    try:
        uhid_input = request.GET.get("uhid", "").strip()
 
        if not uhid_input:
            return Response({
                "status": "error",
                "message": "UHID is required"
            }, status=status.HTTP_400_BAD_REQUEST)
 
        client, db = _get_db()
        bill_col = db["hospital_pharmacybilling"]
 
        cutoff_date = datetime.utcnow() - timedelta(days=30)
 
        # Build query — support partial UHID (numeric suffix after slash)
        # e.g. "7878" should match "S025/007878"
        # We use a regex so partial input works both for exact and substring
        import re
        escaped = re.escape(uhid_input)
 
        query = {
            "uhid":            {"$regex": escaped, "$options": "i"},
            "billing_status":  "Paid",
            "bill_date":       {"$gte": cutoff_date},
        }
 
        bills_cursor = bill_col.find(
            query,
            {
                "_id": 0,
                "bill_no": 1,
                "bill_date": 1,
                "uhid": 1,
                "net_amount": 1,
                "total_amount": 1,
                "billing_mode": 1,
                "inpatient_number": 1,
            }
        ).sort("bill_date", -1)  # newest first
 
        bills = []
        for b in bills_cursor:
            # Normalise bill_date to ISO string for JSON serialisation
            bd = b.get("bill_date")
            if isinstance(bd, datetime):
                bd = bd.isoformat()
 
            bills.append({
                "bill_no":           b.get("bill_no"),
                "bill_date":         bd,
                "uhid":              b.get("uhid"),
                "net_amount":        _convert_decimal(b.get("net_amount", 0)),
                "total_amount":      _convert_decimal(b.get("total_amount", 0)),
                "billing_mode":      b.get("billing_mode", ""),
                "inpatient_number":  b.get("inpatient_number", ""),
            })
 
        client.close()
 
        return Response({
            "status":  "success",
            "message": f"{len(bills)} bill(s) found within the last 30 days.",
            "data":    bills,
        }, status=status.HTTP_200_OK)
 
    except Exception as e:
        return Response({
            "status":     "error",
            "message":    f"Internal server error: {str(e)}",
            "error_type": type(e).__name__,
            "trace":      traceback.format_exc(),
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
 



from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
from bson.decimal128 import Decimal128
from datetime import datetime, timedelta
import os

client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
db = client["HMS"]

bill_collection  = db["hospital_pharmacybilling"]
stock_collection = db["hospital_pharmacystock"]
item_collection  = db["hospital_pharmacyitem"]


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def get_salesreturn_billdetails(request):
    try:
        data = request.data

        # =========================
        # ✅ INPUT VALIDATION
        # =========================
        bill_no = data.get("bill_no")

        if not bill_no:
            return Response({
                "status": "error",
                "message": "Bill number is required to fetch details."
            }, status=status.HTTP_400_BAD_REQUEST)

        # =========================
        # ✅ AUTH DETAILS
        # =========================
        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")

        # =========================
        # ✅ FETCH BILL
        # =========================
        bill = bill_collection.find_one({
            "bill_no": bill_no,
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code,
            "billing_status": "Paid"
        })

        # ❌ BILL NOT FOUND
        if not bill:
            return Response({
                "status": "error",
                "message": f"No paid bill found for Bill No: {bill_no}."
            }, status=status.HTTP_404_NOT_FOUND)

        # =========================
        # ✅ BILL DATE VALIDATION (30 DAYS)
        # Must be within 30 days from TODAY going backwards
        # =========================
        bill_date = bill.get("bill_date")

        if not bill_date:
            return Response({
                "status": "error",
                "message": "Bill date is missing. Unable to process sales return."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Convert string → datetime if needed
        if isinstance(bill_date, str):
            bill_date = datetime.fromisoformat(bill_date)

        # Normalize to date-only (strip time) for fair day comparison
        current_date  = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        bill_date_day = bill_date.replace(hour=0, minute=0, second=0, microsecond=0)
        allowed_from  = current_date - timedelta(days=30)

        if bill_date_day < allowed_from:
            return Response({
                "status": "error",
                "message": (
                    f"Sales return is not allowed. Bill dated "
                    f"{bill_date_day.strftime('%d-%m-%Y')} is older than 30 days. "
                    f"Returns are accepted only within 30 days from the bill date."
                )
            }, status=status.HTTP_400_BAD_REQUEST)

        # =========================
        # ✅ CHECK SALES RETURN STATUS
        # For each item, sum all return_qty entries in edit_history where
        # action == "sales_return", then compare against the billed old_qty.
        #
        # Rules:
        #   • total_returned_qty >= billed_qty  → item is FULLY returned  (exclude)
        #   • 0 < total_returned_qty < billed_qty → item is PARTIALLY returned
        #                                           (include with remaining_qty)
        #   • total_returned_qty == 0            → item never returned (include as-is)
        # =========================
        medicine_particulars = bill.get("medicine_particulars", [])

        def convert_decimal(val):
            return float(val.to_decimal()) if isinstance(val, Decimal128) else val

        # Build a per-item return summary
        # key → (item_id, batch_number)  value → dict with billed_qty & total_returned_qty
        item_return_map = {}

        for item in medicine_particulars:
            key        = (str(item.get("item_id")), str(item.get("batch_number", "")))
            billed_qty = int(item.get("qty", 0))

            # Sum all return_qty values across every sales_return history entry
            total_returned = sum(
                int(h.get("return_qty", 0))
                for h in item.get("edit_history", [])
                if h.get("action") == "sales_return"
            )

            item_return_map[key] = {
                "billed_qty":      billed_qty,
                "total_returned":  total_returned,
                # remaining qty that can still be returned
                "remaining_qty":   max(0, billed_qty - total_returned),
                "fully_returned":  total_returned >= billed_qty and billed_qty > 0,
            }

        total_items         = len(medicine_particulars)
        fully_returned_keys = {k for k, v in item_return_map.items() if v["fully_returned"]}
        partial_keys        = {
            k for k, v in item_return_map.items()
            if not v["fully_returned"] and v["total_returned"] > 0
        }

        # ❌ ALL items fully returned → block the entire bill
        if total_items > 0 and len(fully_returned_keys) == total_items:
            return Response({
                "status": "error",
                "message": (
                    f"Sales return for Bill No: {bill_no} has already been fully processed. "
                    f"All items in this bill have been returned."
                )
            }, status=status.HTTP_400_BAD_REQUEST)

        # =========================
        # ✅ PROCESS ITEMS
        # • Skip fully-returned items entirely
        # • For partially-returned items → show remaining_qty and adjusted calculated_price
        # • For untouched items → show original qty and price
        # =========================
        items_data          = []
        partial_return_count = len(fully_returned_keys)   # how many lines were excluded

        for item in medicine_particulars:
            item_id = item.get("item_id")
            batch   = item.get("batch_number")
            key     = (str(item_id), str(batch or ""))
            summary = item_return_map.get(key, {})

            # ❌ Skip fully-returned items — don't show them at all
            if summary.get("fully_returned"):
                continue

            # Remaining qty to return (original qty if never returned)
            remaining_qty    = summary.get("remaining_qty", item.get("qty", 0))
            billed_qty       = summary.get("billed_qty",    item.get("qty", 0))
            total_returned   = summary.get("total_returned", 0)

            # Pro-rate calculated_price to the remaining qty
            original_calc_price = item.get("calculated_price", 0)
            per_unit_price      = (original_calc_price / billed_qty) if billed_qty > 0 else 0
            remaining_calc_price = round(per_unit_price * remaining_qty, 2)

            # 🔹 ITEM MASTER
            item_master = item_collection.find_one({
                "item_id": item_id,
                "hospital_code": hospital_code,
                "branch_code": branch_code
            })
            item_name = item_master.get("item_name") if item_master else "Unknown Item"

            # 🔹 STOCK DETAILS
            stock = stock_collection.find_one({
                "item_id": item_id,
                "batch_number": batch,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code
            })

            items_data.append({
                "item_id":            item_id,
                "item_name":          item_name,
                "batch_number":       batch,
                # billed_qty = original qty on the bill
                # qty        = remaining qty available for return
                "billed_qty":         billed_qty,
                "already_returned":   total_returned,           # how many already returned
                "qty":                remaining_qty,            # returnable qty
                "price":              item.get("price", 0),
                "calculated_price":   remaining_calc_price,     # pro-rated to remaining qty
                "mrp":                convert_decimal(stock.get("mrp")) if stock else 0,
                "expiry_date":        stock.get("expiry_date") if stock else None,
                "available_stock":    stock.get("total_stock", 0) if stock else 0,
                "blocked_qty":        stock.get("blocked_quantity", 0) if stock else 0,
                "cgst":               convert_decimal(stock.get("CGST_Percentage")) if stock else 0,
                "sgst":               convert_decimal(stock.get("SGST_Percentage")) if stock else 0,
                "is_partial_return":  total_returned > 0,       # flag for frontend badge
            })

        # =========================
        # ✅ SUCCESS RESPONSE
        # =========================
        has_exclusions = len(fully_returned_keys) > 0
        has_partials   = len(partial_keys) > 0

        if has_exclusions and has_partials:
            resp_message = (
                f"{len(fully_returned_keys)} item(s) fully returned (excluded). "
                f"{len(partial_keys)} item(s) partially returned — showing remaining qty."
            )
        elif has_exclusions:
            resp_message = (
                f"{len(fully_returned_keys)} item(s) have already been fully returned and are excluded."
            )
        elif has_partials:
            resp_message = (
                f"{len(partial_keys)} item(s) partially returned — showing remaining returnable qty."
            )
        else:
            resp_message = "Bill details fetched successfully."

        return Response({
            "status": "success",
            "message": resp_message,
            "data": {
                "bill_no":            bill.get("bill_no"),
                "bill_type":          bill.get("bill_type"),
                "uhid":               bill.get("uhid"),
                "bill_date":          bill_date,
                "doctor_id":          bill.get("doctor_id"),
                "total_amount":       bill.get("total_amount"),
                "net_amount":         bill.get("net_amount"),
                "billing_mode":       bill.get("billing_mode"),
                # True when at least one item was excluded or partially returned
                "partially_returned": has_exclusions or has_partials,
                "items":              items_data
            }
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "status": "error",
            "message": f"Internal server error: {str(e)}"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    




    from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import datetime
from pymongo import MongoClient
import os
import json

from ..models import SalesReturn
from ..serializers import SalesReturnSerializer


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def OP_salesreturn_billdetails(request):
    try:
        data = request.data
 
        # =========================
        # ✅ INPUT
        # =========================
        bill_no              = data.get("bill_no")
        uhid                 = data.get("uhid")
        bill_type            = data.get("bill_type")
        medicine_particulars = data.get("medicine_particulars", [])
        return_amount        = data.get("return_amount", "0.00")
        payment_type         = data.get("payment_type", "")
 
        # 🔹 Convert string → list (handles FormData / multipart)
        if isinstance(medicine_particulars, str):
            try:
                medicine_particulars = json.loads(medicine_particulars)
            except Exception:
                return Response({
                    "status":  "error",
                    "message": "medicine_particulars must be a valid JSON array"
                }, status=status.HTTP_400_BAD_REQUEST)
 
        if not isinstance(medicine_particulars, list):
            return Response({
                "status":  "error",
                "message": "medicine_particulars must be an array"
            }, status=status.HTTP_400_BAD_REQUEST)
 
        if not bill_no or not uhid or not medicine_particulars:
            return Response({
                "status":  "error",
                "message": "bill_no, uhid and medicine_particulars are required"
            }, status=status.HTTP_400_BAD_REQUEST)
 
        # =========================
        # ✅ AUTH
        # =========================
        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")
        employee_id   = data.get("auth-user-id")
 
        # =========================
        # ✅ VALIDATE & CLEAN ITEMS
        # =========================
        cleaned_particulars = []
        for item in medicine_particulars:
            if not isinstance(item, dict):
                return Response({
                    "status":  "error",
                    "message": "Each medicine_particular must be an object"
                }, status=status.HTTP_400_BAD_REQUEST)
 
            try:
                billed_qty = float(item.get("billed_qty", 0))
                return_qty = float(item.get("return_qty", 0))
            except Exception:
                return Response({
                    "status":  "error",
                    "message": f"Invalid quantity format for item {item.get('item_id')}"
                }, status=status.HTTP_400_BAD_REQUEST)
 
            if return_qty <= 0:
                return Response({
                    "status":  "error",
                    "message": f"Return quantity must be greater than 0 for item {item.get('item_id')}"
                }, status=status.HTTP_400_BAD_REQUEST)
 
            if return_qty > billed_qty:
                return Response({
                    "status":  "error",
                    "message": f"Return quantity exceeds billed quantity for item {item.get('item_id')}"
                }, status=status.HTTP_400_BAD_REQUEST)
 
            cleaned_particulars.append(item)
 
        # =========================
        # ✅ GENERATE RETURN BILL NO
        # Uses financial year prefix + auto-increment
        # Each submission always gets a fresh unique bill number
        # =========================
        now            = timezone.now()
        current_year   = now.year % 100
        next_year      = (now.year + 1) % 100
        financial_year = f"{current_year:02d}{next_year:02d}"
 
        last_records = SalesReturn.objects.filter(
            return_bill_no__startswith=financial_year
        ).values_list("return_bill_no", flat=True)
 
        max_no = 0
        for bill in last_records:
            try:
                last_part = str(bill).split("/")[-1]
                if last_part.isdigit():
                    max_no = max(max_no, int(last_part))
            except Exception:
                continue
 
        new_no         = max_no + 1
        return_bill_no = f"{financial_year}/{new_no:06d}"
 
        # =========================
        # ✅ MONGO — UPDATE STOCK + PUSH NEW edit_history ENTRY
        # A same bill_no can be returned multiple times (partial returns).
        # Each return gets its own unique return_bill_no and a NEW edit_history
        # object pushed into the item's edit_history array — never overwrites.
        # =========================
        client    = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db        = client["HMS"]
        stock_col = db["hospital_pharmacystock"]
        bill_col  = db["hospital_pharmacybilling"]
 
        for item in cleaned_particulars:
            item_id      = int(item.get("item_id"))
            batch_number = str(item.get("batch_number"))
            return_qty   = float(item.get("return_qty", 0))
            billed_qty   = float(item.get("billed_qty", 0))
 
            # ─── 1. STOCK: update lastmodified_date only ──────────────────────
            # sales_return_quantity and sales_return_ref_id are NOT updated here
            stock_result = stock_col.update_one(
                {
                    "item_id":      item_id,
                    "batch_number": batch_number,
                    "outlet_code":  outlet_code
                },
                {
                    "$set": {
                        "lastmodified_date": datetime.utcnow()
                    }
                }
            )
 
            if stock_result.matched_count == 0:
                client.close()
                return Response({
                    "status":  "error",
                    "message": f"Stock not found for item_id {item_id}, batch {batch_number}"
                }, status=status.HTTP_400_BAD_REQUEST)
 
            # ─── 2. BILL: push a NEW edit_history entry ───────────────────────
            # We do NOT guard against the same bill_no being returned again —
            # that is intentional (each partial return pushes a fresh entry with
            # a new return_bill_no). What we guard is the exact same
            # return_bill_no being pushed twice (duplicate submission).
            duplicate_check = bill_col.find_one(
                {
                    "bill_no":       bill_no,
                    "hospital_code": hospital_code,
                    "branch_code":   branch_code,
                    "outlet_code":   outlet_code,
                    "medicine_particulars": {
                        "$elemMatch": {
                            "item_id":                     item_id,
                            "batch_number":                batch_number,
                            "edit_history.return_bill_no": return_bill_no   # this exact return
                        }
                    }
                }
            )
 
            if duplicate_check:
                client.close()
                return Response({
                    "status":  "error",
                    "message": (
                        f"Return bill {return_bill_no} already recorded for item {item_id} "
                        f"batch {batch_number}. Duplicate submission blocked."
                    )
                }, status=status.HTTP_400_BAD_REQUEST)
 
            # ─── Compute old_qty = original_qty − total already returned ─────
            # Fetch the current bill document to read the item's existing
            # edit_history, sum all previous return_qty entries, and derive
            # the correct old_qty for THIS new history entry.
            #
            # Example:
            #   original qty  = 5
            #   1st return    → old_qty: 5,  return_qty: 2  (remaining after: 3)
            #   2nd return    → old_qty: 3,  return_qty: 1  (remaining after: 2)
            #   3rd return    → old_qty: 2,  return_qty: 1  (remaining after: 1)
            current_bill = bill_col.find_one(
                {
                    "bill_no":       bill_no,
                    "hospital_code": hospital_code,
                    "branch_code":   branch_code,
                    "outlet_code":   outlet_code,
                },
                # Only project the matching medicine_particular to keep it lean
                {"medicine_particulars": 1, "_id": 0}
            )
 
            # Find the matching item in the returned document
            original_qty         = billed_qty   # fallback: use what frontend sent
            total_prev_returned  = 0.0
 
            if current_bill:
                for mp in current_bill.get("medicine_particulars", []):
                    if (int(mp.get("item_id", -1)) == item_id and
                            str(mp.get("batch_number", "")) == batch_number):
                        # Original qty is stored as `qty` on the billing document
                        original_qty = float(mp.get("qty", billed_qty))
                        # Sum every previous sales_return entry
                        total_prev_returned = sum(
                            float(h.get("return_qty", 0))
                            for h in mp.get("edit_history", [])
                            if h.get("action") == "sales_return"
                        )
                        break
 
            # old_qty for this entry = qty remaining just BEFORE this return
            computed_old_qty = original_qty - total_prev_returned
 
            history_entry = {
                "action":         "sales_return",
                "old_qty":        computed_old_qty,   # ✅ remaining qty before this return
                "return_qty":     return_qty,
                "return_bill_no": return_bill_no,
                "return_date":    datetime.utcnow().isoformat(),
                "edited_by":      employee_id
            }
 
            bill_result = bill_col.update_one(
                {
                    "bill_no":       bill_no,
                    "hospital_code": hospital_code,
                    "branch_code":   branch_code,
                    "outlet_code":   outlet_code,
                },
                {
                    "$push": {
                        "medicine_particulars.$[elem].edit_history": history_entry
                    },
                    "$set": {
                        "lastmodified_by":   employee_id,
                        "lastmodified_date": datetime.utcnow()
                    }
                },
                array_filters=[
                    {
                        "elem.item_id":      item_id,
                        "elem.batch_number": batch_number
                    }
                ]
            )
 
            if bill_result.matched_count == 0:
                client.close()
                return Response({
                    "status":  "error",
                    "message": f"Item {item_id} batch {batch_number} not found in bill {bill_no}"
                }, status=status.HTTP_400_BAD_REQUEST)
 
        client.close()
 
        # =========================
        # ✅ SAVE TO DJANGO (SalesReturn model)
        # medicine_particulars must be serialised to JSON string if the model
        # field is TextField / CharField. If it is a JSONField, pass the list
        # directly. We serialise to string here to be safe for both.
        # =========================
        mp_to_store = (
            json.dumps(cleaned_particulars)          # TextField / CharField
            if not hasattr(SalesReturn.medicine_particulars, 'field') or
               SalesReturn._meta.get_field("medicine_particulars").get_internal_type()
               not in ("JSONField",)
            else cleaned_particulars                 # JSONField — pass list directly
        )
 
        sales_return = SalesReturn.objects.create(
            return_bill_no       = return_bill_no,
            bill_no              = bill_no,
            uhid                 = uhid,
            bill_type            = bill_type,
            return_amount        = return_amount,
            medicine_particulars = mp_to_store,      # ← always safe type now
            hospital_code        = hospital_code,
            branch_code          = branch_code,
            outlet_code          = outlet_code,
            pharmacist_id        = employee_id,
            PaymentType          = payment_type,
            created_by           = employee_id,
            status               = "Pending"
        )
 
        serializer = SalesReturnSerializer(sales_return)
        return Response({
            "status":  "success",
            "message": f"Sales return {return_bill_no} processed successfully.",
            "data":    serializer.data
        }, status=status.HTTP_201_CREATED)
 
    except Exception as e:
        return Response({
            "status":     "error",
            "message":    f"Internal server error: {str(e)}",
            "error_type": type(e).__name__
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
 

