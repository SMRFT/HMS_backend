from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.db.models import Q
from datetime import datetime
import os
from pymongo import MongoClient
from ...models import Patient, PharmacyBilling, Cashcountershiftdetails
from pyauth.auth import HasRoleAndDataPermission

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def shift_basis_accounts_report(request):
    try:
        # 1. Extract params
        if request.method == "POST":
            data = request.data
        else:
            data = request.query_params

        from_date_str = data.get("from_date")
        to_date_str = data.get("to_date")
        outlet_code_filter = data.get("outlet_code")
        shiftno_filter = data.get("shiftno")

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

        # 3. Connect MongoDB
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]
        
        # Helper to convert MongoDB decimal/date
        def clean_val(v):
            from bson import Decimal128
            if v is None: return ""
            if isinstance(v, Decimal128): return float(v.to_decimal())
            if isinstance(v, datetime): return v.isoformat()
            return v

        def clean_amt(v):
            from bson import Decimal128
            if v is None: return 0.0
            if isinstance(v, Decimal128): return float(v.to_decimal())
            try: return float(v)
            except: return 0.0

        report_data = []
        
        # Query Builder for Mongo
        # We search by created_date or specific bill date depending on collection
        mongo_query = {}
        if hospital_code: mongo_query["hospital_code"] = hospital_code
        if branch_code: mongo_query["branch_code"] = branch_code
        if outlet_code_filter and outlet_code_filter != "all":
            mongo_query["outlet_code"] = outlet_code_filter
        if shiftno_filter:
            mongo_query["shiftno"] = shiftno_filter

        # COLLECTIONS TO SCAN
        # format: (collection_name, date_field, type_label, id_field, amt_field, status_query, uhid_field)
        scans = [
            ("hospital_billing", "created_date", "Registration", "bill_number", "total_fees", {"payment_status": "Paid"}, "uhid"),
            ("hospital_investbilling", "investBillDate", "Investigation", "investBillNo", "finalPrice", {"paymentStatus": "Paid"}, "uhid"),
            ("hospital_pharmacybilling", "bill_date", "Pharmacy", "bill_no", "net_amount", {"billing_status": "Paid"}, "uhid"),
            ("hospital_dischargebilling", "bill_date", "Discharge", "bill_no", "net_amount", {"status": "Paid"}, "uhid"),
            ("hospital_receiptandpayment", "created_date", "Receipt", "voucher_no", "amount", {"receipt_type": "Receipt"}, None),
            ("hospital_receiptandpayment", "created_date", "Payment", "voucher_no", "amount", {"receipt_type": "Payment"}, None),
        ]

        for col_name, date_f, label, id_f, amt_f, status_q, uhid_f in scans:
            q = mongo_query.copy()
            q.update(status_q)
            
            # Date filter only if shiftno is NOT provided (if shiftno is provided, we want all items in that shift regardless of date)
            if not shiftno_filter:
                q[date_f] = {"$gte": from_date, "$lte": to_date}
            
            docs = list(db[col_name].find(q))
            for d in docs:
                amt = clean_amt(d.get(amt_f, 0))
                # For payments, we treat as negative for net total
                display_amt = -amt if label == "Payment" else amt
                
                # Extract items if they exist
                items = d.get("items") or d.get("item") or []
                
                report_data.append({
                    "type": label,
                    "bill_no": d.get(id_f),
                    "bill_date": clean_val(d.get(date_f)),
                    "uhid": d.get(uhid_f) if uhid_f else "",
                    "patient_name": "", # Will fill later
                    "net_amount": amt,
                    "display_amount": display_amt,
                    "payment_mode": d.get("payment_mode") or d.get("paymentMethod") or d.get("payment_method") or "Cash",
                    "outlet_code": d.get("outlet_code"),
                    "shiftno": d.get("shiftno"),
                    "cashier_id": d.get("cashier_id") or d.get("created_by") or d.get("CashierID"),
                    "status": "Paid",
                    "items": clean_val(items) # Sanitize items list
                })

        # 4. Fetch Patient Names
        uhids = list(set([r["uhid"] for r in report_data if r["uhid"]]))
        patients = list(db["hospital_patient"].find({"uhid": {"$in": uhids}}, {"uhid": 1, "firstName": 1, "lastName": 1}))
        patient_map = {p["uhid"]: f"{p['firstName']} {p['lastName']}" for p in patients}
        
        # 5. Fetch Cashier Names (Global DB)
        cashier_ids = list(set([r["cashier_id"] for r in report_data if r["cashier_id"]]))
        cashier_name_map = {}
        try:
            g_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            g_db = g_client['Global']
            profiles = list(g_db['backend_diagnostics_profile'].find(
                {"employeeId": {"$in": cashier_ids}},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            ))
            cashier_name_map = {p['employeeId']: p['employeeName'] for p in profiles}
            g_client.close()
        except: pass

        # Final Polish
        total_net = 0
        for r in report_data:
            r["patient_name"] = patient_map.get(r["uhid"], "N/A") if r["uhid"] else "N/A"
            r["cashier_name"] = cashier_name_map.get(r["cashier_id"], r["cashier_id"])
            total_net += r["display_amount"]

        client.close()
        
        # Sort by date
        report_data.sort(key=lambda x: x["bill_date"] or "", reverse=True)

        return Response({
            "success": True,
            "summary": {
                "total_net": round(total_net, 2),
                "count": len(report_data),
                # Breakdown by type
                "breakdown": {
                    label: round(sum(r["display_amount"] for r in report_data if r["type"] == label), 2)
                    for label in set(r["type"] for r in report_data)
                }
            },
            "data": report_data
        })

    except Exception as e:
        print("Report Error:", str(e))
        return Response({"success": False, "message": str(e)}, status=500)
