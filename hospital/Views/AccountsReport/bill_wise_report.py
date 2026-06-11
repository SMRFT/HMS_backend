from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from datetime import datetime
import os
from pymongo import MongoClient
from pyauth.auth import HasRoleAndDataPermission
from .accounting_reports import fetch_detailed_billing_data

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
        hospital_code = (
            data.get("auth-hospital-code") or 
            request.META.get("HTTP_AUTH_HOSPITAL_CODE") or 
            request.META.get("HTTP_HOSPITAL_CODE") or 
            (request.headers.get("hospital-code") if hasattr(request, "headers") else None)
        )
        branch_code = (
            data.get("auth-branch-code") or 
            request.META.get("HTTP_AUTH_BRANCH_CODE") or 
            request.META.get("HTTP_BRANCH_CODE") or 
            (request.headers.get("branch-code") if hasattr(request, "headers") else None)
        )

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
        
        # Query Builder for Cash Counter Collection
        mongo_query = {}
        if hospital_code: mongo_query["hospital_code"] = hospital_code
        if branch_code: mongo_query["branch_code"] = branch_code
        mongo_query["created_date"] = {"$gte": from_date, "$lte": to_date}

        ccc_docs = list(db["hospital_cashcountercollection"].find(mongo_query))
        
        # Enrich the records
        enriched_data = fetch_detailed_billing_data(db, ccc_docs)
        
        # Filter by type and patient
        report_data = []
        for r in enriched_data:
            # Map type representation for filter checks
            mapped_type = r["type"]
            if mapped_type in ["OPPharmacyBills", "Pharmacy", "PharmacyBills"]:
                r["type"] = "Pharmacy"
            elif mapped_type in ["Investigation", "InvestigationBills"]:
                r["type"] = "Investigation"
            elif mapped_type in ["Billing", "Registration", "RegistrationBills"]:
                r["type"] = "Registration"
            elif mapped_type in ["Discharge", "DischargeBills"]:
                r["type"] = "Discharge"
            elif mapped_type in ["IPAdvance", "IPAdvanceBills"]:
                r["type"] = "IPAdvance"
            elif mapped_type in ["Sales Return", "sales_return"]:
                r["type"] = "Sales Return"
                
            if type_filter and type_filter != "All" and type_filter != r["type"]:
                continue
            if patient_filter and patient_filter != r["uhid"]:
                continue
                
            report_data.append(r)

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
