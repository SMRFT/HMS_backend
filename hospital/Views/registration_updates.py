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
        
        employee_id = data.get('auth-user-id', 'system')
        hospital_code = data.get('auth-hospital-code', 'system')

        if not bill_number:
            return Response({"success": False, "message": "Bill number is required"}, status=400)

        bill = Billing.objects.get(bill_number=bill_number)
        
        if bill.payment_status == 'Paid':
            return Response({"success": False, "message": "Cannot edit a paid bill"}, status=400)

        # Prepare history log
        history_entry = {
            "date": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user": employee_id,
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
        remarks = data.get('remarks', 'Patient Request')
        
        employee_id = data.get('auth-user-id', 'system')
        hospital_code = data.get('auth-hospital-code', 'system')
        branch_code = data.get('auth-branch-code', 'system')
        outlet_code = data.get('auth-outlet-code', 'system')

        if not all([bill_no, uhid, refund_amount]):
            return Response({"success": False, "message": "Missing required fields"}, status=400)

        # Check if bill exists and is paid
        bill = Billing.objects.get(bill_number=bill_no)
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
            bill_type=bill.billtype,
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
            "changes": {
                "refund": {
                    "refund_bill_no": refund.refund_bill_no,
                    "amount": str(refund_amt_dec),
                    "status": refund.status
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
