from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from datetime import datetime
import os
from pymongo import MongoClient
from pyauth.auth import HasRoleAndDataPermission

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def bill_wise_report(request):
    try:
        # 1. Extract params
        if request.method == "POST":
            data = request.data
        else:
            data = request.query_params

        from_date_str = data.get("from_date")
        to_date_str = data.get("to_date")
        type_filter = data.get("bill_type") # "All", "Pharmacy", "Investigation", etc.
        patient_filter = data.get("uhid")
        
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
        mongo_query = {}
        if hospital_code: mongo_query["hospital_code"] = hospital_code
        if branch_code: mongo_query["branch_code"] = branch_code
        if patient_filter: mongo_query["uhid"] = patient_filter

        # COLLECTIONS TO SCAN
        # format: (collection_name, date_field, type_label, id_field, amt_field, status_query, uhid_field)
        scans = [
            ("hospital_billing", "created_date", "Registration", "bill_number", "total_fees", {"payment_status": "Paid"}, "uhid"),
            ("hospital_investbilling", "investBillDate", "Investigation", "investBillNo", "finalPrice", {"paymentStatus": "Paid"}, "uhid"),
            ("hospital_pharmacybilling", "bill_date", "Pharmacy", "bill_no", "net_amount", {"billing_status": "Paid"}, "uhid"),
            ("hospital_dischargebilling", "bill_date", "Discharge", "bill_no", "net_amount", {"status": "Paid"}, "uhid"),
            ("hospital_salesreturn", "return_bill_date", "Sales Return", "return_bill_no", "medicine_particulars", {}, "uhid"),
        ]

        for col_name, date_f, label, id_f, amt_f, status_q, uhid_f in scans:
            if type_filter and type_filter != "All" and type_filter != label:
                continue

            q = mongo_query.copy()
            q.update(status_q)
            q[date_f] = {"$gte": from_date, "$lte": to_date}
            
            docs = list(db[col_name].find(q))
            for d in docs:
                # Handle Sales Return specially to sum up prices
                if label == "Sales Return":
                    meds = d.get("medicine_particulars", [])
                    if isinstance(meds, str):
                        import json
                        try: meds = json.loads(meds)
                        except: meds = []
                    
                    # Calculate total return amount
                    amt = 0.0
                    for m in meds:
                        # item format: {"item_id": 1, "return_qty": 1, "price": 21.24, ...}
                        qty = float(m.get("return_qty", 0))
                        price = float(m.get("price", 0))
                        amt += qty * price
                    
                    display_amt = -amt # Returns are negative
                    items = meds
                else:
                    amt = clean_amt(d.get(amt_f, 0))
                    display_amt = amt
                    items = d.get("items") or d.get("item") or d.get("medicine_particulars") or []

                report_data.append({
                    "type": label,
                    "bill_no": d.get(id_f),
                    "bill_date": clean_val(d.get(date_f)),
                    "uhid": d.get(uhid_f) if uhid_f else "",
                    "patient_name": "", # Will fill later
                    "net_amount": round(amt, 2),
                    "display_amount": round(display_amt, 2),
                    "payment_mode": d.get("payment_mode") or d.get("paymentMethod") or d.get("payment_method") or "Cash",
                    "cashier_id": d.get("cashier_id") or d.get("created_by") or d.get("CashierID"),
                    "items": clean_val(items)
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
        total_collection = 0
        total_return = 0
        
        for r in report_data:
            r["patient_name"] = patient_map.get(r["uhid"], "N/A") if r["uhid"] else "N/A"
            r["cashier_name"] = cashier_name_map.get(r["cashier_id"], r["cashier_id"])
            
            if r["type"] == "Sales Return":
                total_return += abs(r["display_amount"])
            else:
                total_collection += r["display_amount"]

        client.close()
        
        # Sort by date
        report_data.sort(key=lambda x: x["bill_date"] or "", reverse=True)

        return Response({
            "success": True,
            "summary": {
                "total_collection": round(total_collection, 2),
                "total_return": round(total_return, 2),
                "net_collection": round(total_collection - total_return, 2),
                "count": len(report_data),
                "breakdown": {
                    label: round(sum(r["display_amount"] for r in report_data if r["type"] == label), 2)
                    for label in set(r["type"] for r in report_data)
                }
            },
            "data": report_data
        })

    except Exception as e:
        import traceback
        print("Bill Wise Report Error:", str(e))
        print(traceback.format_exc())
        return Response({"success": False, "message": str(e)}, status=500)
