from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.db.models import Q
from datetime import datetime
import os
from pymongo import MongoClient
from ..models import Patient, PharmacyBilling, Cashcountershiftdetails
from pyauth.auth import HasRoleAndDataPermission

@api_view(["GET", "POST"])
# @permission_classes([HasRoleAndDataPermission])
def pharmacy_sales_report(request):
    try:
        # 1. Extract params
        if request.method == "POST":
            data = request.data
        else:
            data = request.query_params

        from_date_str = data.get("from_date")
        to_date_str = data.get("to_date")
        outlet_code_filter = data.get("outlet_code")

        # AUTH CODES
        hospital_code = data.get("auth-hospital-code")
        branch_code = data.get("auth-branch-code")

        # 2. Date normalization
        if not from_date_str:
            from_date_str = datetime.now().strftime("%Y-%m-%d")
        if not to_date_str:
            to_date_str = datetime.now().strftime("%Y-%m-%d")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

        # 3. Query PharmacyBilling
        query = Q(bill_date__range=[from_date, to_date]) | Q(created_date__range=[from_date, to_date])
        query &= Q(billing_status__in=["Billed", "Paid"])
        
        if hospital_code:
            query &= Q(hospital_code=hospital_code)
        if branch_code:
            query &= Q(branch_code=branch_code)
            
        if outlet_code_filter and outlet_code_filter != "all":
            query &= Q(outlet_code=outlet_code_filter)
        
        bills = PharmacyBilling.objects.filter(query).order_by("-bill_date")

        # 4. Fetch Shift Details, Patient Names & Cashier Names
        shift_nos = list(set([b.shiftno for b in bills if b.shiftno]))
        uhids = list(set([b.uhid for b in bills if b.uhid]))

        # Shift Map
        shifts = Cashcountershiftdetails.objects.filter(shiftno__in=shift_nos)
        shift_map = {s.shiftno: s for s in shifts}
        
        # Cashier IDs for name lookup
        cashier_ids = list(set([s.CashierID for s in shifts if s.CashierID]))
        cashier_ids.extend(list(set([b.cashier_id for b in bills if b.cashier_id])))
        cashier_ids = list(set([c for c in cashier_ids if c]))

        # Patient Map
        patients = Patient.objects.filter(uhid__in=uhids)
        patient_map = {p.uhid: f"{p.firstName} {p.lastName}" for p in patients}
        
        # Cashier Name Map (from Global DB)
        cashier_name_map = {}
        try:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            db = client['Global']
            profiles = list(db['backend_diagnostics_profile'].find(
                {"employeeId": {"$in": cashier_ids}},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            ))
            cashier_name_map = {p['employeeId']: p['employeeName'] for p in profiles}
            client.close()
        except Exception as e:
            print("Error fetching cashier names:", e)

        # 5. Build Result
        report_data = []
        total_sales = 0
        total_discount = 0
        total_net = 0

        for b in bills:
            shift = shift_map.get(b.shiftno)
            cashier_id = b.cashier_id or (shift.CashierID if shift else "")
            report_data.append({
                "bill_no": b.bill_no,
                "bill_date": b.bill_date or b.created_date,
                "uhid": b.uhid,
                "patient_name": patient_map.get(b.uhid, ""),
                "total_amount": b.total_amount,
                "discount_amount": b.overall_discount_amount,
                "net_amount": b.net_amount,
                "payment_mode": b.payment_mode,
                "outlet_code": b.outlet_code,
                "shiftno": b.shiftno,
                "cashier_id": cashier_id,
                "cashier_name": cashier_name_map.get(cashier_id, cashier_id),
                "billing_status": b.billing_status
            })
            total_sales += b.total_amount
            total_discount += b.overall_discount_amount
            total_net += b.net_amount

        return Response({
            "success": True,
            "summary": {
                "total_sales": round(total_sales, 2),
                "total_discount": round(total_discount, 2),
                "total_net": round(total_net, 2),
                "count": len(report_data)
            },
            "data": report_data
        })

    except Exception as e:
        print("Report Error:", str(e))
        return Response({"success": False, "message": str(e)}, status=500)
