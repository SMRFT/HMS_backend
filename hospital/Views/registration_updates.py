from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Q
from ..models import Billing, Refund, Patient
from pyauth.auth import HasRoleAndDataPermission
from decimal import Decimal
import traceback

@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def update_registration_visit(request):
    """
    Updates the doctor and fees for an existing registration billing record.
    """
    try:
        data = request.data
        bill_number = data.get('bill_number')
        new_doctor_id = data.get('doctor_id')
        doctor_name = data.get('doctorName')
        registration_fee = data.get('registrationFee')
        consulting_fee = data.get('consultingFee')
        total_fees = data.get('totalFees')
        
        employee_id = request.headers.get('auth-user-id') or data.get('auth-user-id') or data.get('employee_id') or 'system'
        hospital_code = request.headers.get('hospital-code') or data.get('auth-hospital-code') or 'system'

        # Resolve employee name for history log
        user_name = employee_id
        if employee_id and employee_id != 'system':
            try:
                import os
                from pymongo import MongoClient
                mongo_host = os.getenv("GLOBAL_DB_HOST")
                if mongo_host:
                    client = MongoClient(mongo_host)
                    global_db = client['Global']
                    diag_collection = global_db['backend_diagnostics_profile']
                    u_doc = diag_collection.find_one({"employeeId": employee_id}, {"employeeName": 1})
                    if u_doc and u_doc.get("employeeName"):
                        user_name = u_doc.get("employeeName")
            except Exception:
                pass

        reason = data.get('reason') or data.get('edit_reason')
        if not reason or not str(reason).strip():
            return Response({"success": False, "message": "Reason for editing visit is required"}, status=400)
        reason = str(reason).strip()

        if not bill_number:
            return Response({"success": False, "message": "Bill number is required"}, status=400)

        bill = Billing.objects.get(bill_number=bill_number)
        
        if bill.payment_status == 'Paid':
            return Response({"success": False, "message": "Cannot edit a paid bill"}, status=400)

        # Prepare history log
        history_entry = {
            "date": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user": user_name,
            "reason": reason,
            "changes": {}
        }
        
        # Update fields and log changes
        if new_doctor_id and bill.doctor_id != new_doctor_id:
            history_entry["changes"]["doctor"] = {"old": bill.doctor_id, "new": new_doctor_id}
            bill.doctor_id = new_doctor_id
            
        if doctor_name:
            bill.patient.doctorName = doctor_name
            bill.patient.save()
            
        def to_dec(val):
            if val is None: return Decimal('0.00')
            if hasattr(val, 'to_decimal'): return val.to_decimal()
            return Decimal(str(val))

        reg_fee_dec = to_dec(registration_fee)
        if reg_fee_dec != to_dec(bill.registration_fee):
            history_entry["changes"]["registration_fee"] = {"old": str(bill.registration_fee), "new": str(reg_fee_dec)}
            bill.registration_fee = reg_fee_dec

        cons_fee_dec = to_dec(consulting_fee)
        if cons_fee_dec != to_dec(bill.consulting_fee):
            history_entry["changes"]["consulting_fee"] = {"old": str(bill.consulting_fee), "new": str(cons_fee_dec)}
            bill.consulting_fee = cons_fee_dec

        total_fees_dec = to_dec(total_fees)
        if total_fees_dec != to_dec(bill.total_fees):
            history_entry["changes"]["total_fees"] = {"old": str(bill.total_fees), "new": str(total_fees_dec)}
            bill.total_fees = total_fees_dec

        if history_entry["changes"]:
            if not isinstance(bill.edit_history, list):
                bill.edit_history = []
            bill.edit_history.append(history_entry)

        bill.lastmodified_by = employee_id
        bill.hospital_code = hospital_code
        bill.save()

        return Response({
            "success": True,
            "message": "Visit updated successfully",
            "data": {
                "bill_number": bill.bill_number,
                "doctor": bill.doctor_id
            }
        })

    except Billing.DoesNotExist:
        return Response({"success": False, "message": "Bill not found"}, status=404)
    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)

@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def process_registration_refund(request):
    """
    Processes a refund for a paid registration bill.
    """
    try:
        data = request.data
        bill_no = data.get('bill_no')
        uhid = data.get('uhid')
        refund_amount = data.get('refund_amount')
        reason = data.get('reason') or data.get('remarks')
        if not reason or not str(reason).strip():
            return Response({"success": False, "message": "Reason for processing refund is required"}, status=400)
        remarks = str(reason).strip()
        
        employee_id = data.get('auth-user-id', 'system')
        hospital_code = data.get('auth-hospital-code', 'system')
        branch_code = data.get('auth-branch-code', 'system')
        outlet_code = data.get('auth-outlet-code', 'system')

        if not all([bill_no, uhid, refund_amount]):
            return Response({"success": False, "message": "Missing required fields"}, status=400)

        # Check if bill exists and is paid
        bill = None
        try:
            bill = Billing.objects.get(bill_number=bill_no)
        except Billing.DoesNotExist:
            clean_b = str(bill_no).replace('/', '')
            bill = Billing.objects.filter(
                Q(bill_number=clean_b) |
                Q(bill_number__iexact=bill_no) |
                Q(bill_no=bill_no) |
                Q(bill_no=clean_b)
            ).first()
            if not bill:
                return Response({"success": False, "message": f"Bill '{bill_no}' not found"}, status=404)

        if bill.payment_status != 'Paid':
            return Response({"success": False, "message": "Only paid bills can be refunded"}, status=400)

        # Helper to handle Decimal128 from Djongo
        def to_dec(val):
            if val is None: return Decimal('0.00')
            try:
                if hasattr(val, 'to_decimal'): # Decimal128
                    d = val.to_decimal()
                else:
                    d = Decimal(str(val))
                return d.quantize(Decimal('0.01'))
            except:
                return Decimal('0.00')

        # Calculate refund totals
        previous_refunds = Refund.objects.filter(bill_no=bill_no)
        total_refunded_so_far = sum([to_dec(r.refund_amount) for r in previous_refunds])
        
        advance_amount = to_dec(bill.total_fees)
        refund_amt_dec = to_dec(refund_amount)
        new_total_refunded = total_refunded_so_far + refund_amt_dec
        remaining_balance = advance_amount - new_total_refunded

        if new_total_refunded > advance_amount:
            return Response({"success": False, "message": f"Refund amount exceeds bill total. Max refundable: {advance_amount - total_refunded_so_far}"}, status=400)

        # Create Refund record
        refund = Refund.objects.create(
            bill_no=bill_no,
            uhid=uhid,
            refund_amount=refund_amt_dec,
            bill_type=getattr(bill, 'bill_type', None),
            remarks=remarks,
            status='Pending',
            created_by=employee_id,
            lastmodified_by=employee_id,
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code,
            refund_date=timezone.now()
        )

        # Add to bill history
        history_entry = {
            "date": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user": employee_id,
            "reason": remarks,
            "changes": {
                "refund": {
                    "refund_bill_no": refund.refund_bill_no,
                    "amount": str(refund_amt_dec),
                    "status": refund.status,
                    "reason": remarks
                }
            }
        }
        if not isinstance(bill.edit_history, list):
            bill.edit_history = []
        bill.edit_history.append(history_entry)

        # Update bill status if fully refunded
        if remaining_balance <= 0:
            bill.payment_status = 'Refunded'
        
        bill.save()

        return Response({
            "success": True,
            "message": "Refund processed successfully",
            "refund_bill_no": refund.refund_bill_no
        })

    except Billing.DoesNotExist:
        return Response({"success": False, "message": "Bill not found"}, status=404)
    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def cancel_pending_registration_visit(request):
    """
    Cancels an unpaid (Pending) OP registration / consultation visit before payment.
    Sets is_active=False and payment_status='Cancelled' on the root document, and
    stores all cancellation metadata (is_cancelled, cancel_reason, cancelled_by,
    cancelled_by_id, cancelled_date, lastmodified_by, lastmodified_date) inside edit_history.
    """
    try:
        import os
        from pymongo import MongoClient

        data = request.data
        bill_no = str(data.get('bill_no') or data.get('bill_number') or '').strip()
        reason = str(data.get('reason') or data.get('remarks') or '').strip()

        if not bill_no:
            return Response({"success": False, "message": "Bill number is required"}, status=400)
        if not reason:
            return Response({"success": False, "message": "Reason for cancellation is required"}, status=400)

        employee_id = str(
            request.headers.get('auth-user-id')
            or data.get('auth-user-id')
            or data.get('employee_id')
            or getattr(request.user, 'username', None)
            or 'system'
        ).strip()

        mongo_host = os.getenv("GLOBAL_DB_HOST")
        if not mongo_host:
            return Response({"success": False, "message": "Database configuration missing"}, status=500)

        client = MongoClient(mongo_host, serverSelectionTimeoutMS=5000)
        hms_db = client['HMS']
        global_db = client['Global']

        # Resolve staff display name
        user_name = employee_id
        if employee_id and employee_id != 'system':
            try:
                u_doc = global_db['backend_diagnostics_profile'].find_one(
                    {"employeeId": employee_id},
                    {"employeeName": 1}
                )
                if u_doc and u_doc.get("employeeName"):
                    user_name = str(u_doc.get("employeeName")).strip()
            except Exception:
                pass

        # Support variations with or without slash
        raw_variants = [bill_no]
        if "/" in bill_no:
            raw_variants.append(bill_no.replace("/", ""))
        elif len(bill_no) == 10 and bill_no[:4].isdigit():
            raw_variants.append(f"{bill_no[:4]}/{bill_no[4:]}")

        match_query = {
            "$or": [
                {"bill_number": {"$in": raw_variants}},
                {"bill_no": {"$in": raw_variants}}
            ]
        }

        bill_doc = hms_db["hospital_billing"].find_one(match_query)
        if not bill_doc:
            client.close()
            return Response({"success": False, "message": f"Bill '{bill_no}' not found"}, status=404)

        old_status = str(bill_doc.get("payment_status") or "Pending").strip()
        if old_status.lower() in ("paid", "refunded"):
            client.close()
            return Response({
                "success": False,
                "message": f"Cannot cancel a {old_status} bill here. Please use the Refund workflow."
            }, status=400)

        already_cancelled = (
            bill_doc.get("is_active") is False
            or old_status.lower() == "cancelled"
            or any(isinstance(h, dict) and h.get("is_cancelled") for h in (bill_doc.get("edit_history") or []))
        )
        if already_cancelled:
            client.close()
            return Response({"success": False, "message": "Visit is already cancelled"}, status=400)

        now_utc = timezone.now()

        history_entry = {
            "date": now_utc,
            "user": user_name,
            "reason": reason,
            "is_cancelled": True,
            "cancel_reason": reason,
            "cancelled_by": user_name,
            "cancelled_by_id": employee_id,
            "cancelled_date": now_utc,
            "lastmodified_by": employee_id,
            "lastmodified_date": now_utc,
            "changes": {
                "status": {"old": old_status, "new": "Cancelled"},
                "is_active": {"old": bill_doc.get("is_active", True), "new": False},
                "action": "cancel_before_payment"
            }
        }

        hms_db["hospital_billing"].update_one(
            {"_id": bill_doc["_id"]},
            {
                "$set": {
                    "is_active": False,
                    "payment_status": "Cancelled",
                    "lastmodified_by": employee_id,
                    "lastmodified_date": now_utc
                },
                "$push": {
                    "edit_history": history_entry
                }
            }
        )

        import pytz
        ist_str = now_utc.astimezone(pytz.timezone("Asia/Kolkata")).strftime("%d-%m-%Y %I:%M %p")
        client.close()

        return Response({
            "success": True,
            "message": "Pending visit cancelled successfully",
            "bill_number": bill_doc.get("bill_number") or bill_no,
            "history_entry": {
                "date": ist_str,
                "user": user_name,
                "reason": reason,
                "is_cancelled": True,
                "cancel_reason": reason,
                "cancelled_by": user_name,
                "cancelled_by_id": employee_id,
                "cancelled_date": ist_str,
                "changes": history_entry["changes"]
            }
        })

    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)
