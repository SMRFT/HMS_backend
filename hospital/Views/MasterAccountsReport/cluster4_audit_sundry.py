"""
Cluster 4: Auditing & Sundry Income APIs
========================================
1. Accounts Audit Report
2. Bill Wise Detailed Report
3. Miscellaneous Payment Report
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from datetime import datetime, timedelta
from .core_ledger_engine import AccountsLedgerEngine, clean_num, get_db, parse_date, format_dt, format_ist_time, format_ist_date, format_ist_datetime, to_ist

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def accounts_audit_report_api(request):
    """
    Dedicated Accounts Audit Report API.
    Transactional audit trail across all vouchers, bills, and payment splits matching AuditReport.js.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet")
        )
        
        from .core_ledger_engine import get_db, parse_date
        client, db, g_db = get_db()
        audit_rows = []
        by_source = {
            "Registration Billing": 0,
            "Pharmacy Billing": 0,
            "Sales Return": 0,
            "Investigation Billing": 0
        }
        
        try:
            f_d = parse_date(data.get("from_date") or data.get("start_date"))
            t_d = parse_date(data.get("to_date") or data.get("end_date"), is_end=True)
            
            # 1. Edit History from Registration
            b_edits = list(db["hospital_billing"].find({"edit_history": {"$exists": True, "$ne": []}}))
            for b in b_edits:
                for eh in (b.get("edit_history") or []):
                    if not isinstance(eh, dict): continue
                    dt_s = format_ist_date(eh.get("edited_date") or b.get("billed_date"))
                    if f_d and dt_s < str(f_d)[:10]: continue
                    if t_d and dt_s > str(t_d)[:10]: continue
                    audit_rows.append({
                        "source": "Registration Billing",
                        "record_no": b.get("bill_number") or b.get("bill_no"),
                        "uhid": b.get("uhid") or "",
                        "patient_name": b.get("patient_name") or "Patient",
                        "description": eh.get("description") or eh.get("reason") or "Billing Rate / Fee Modification",
                        "old_value": str(eh.get("old_value") if eh.get("old_value") is not None else "-"),
                        "new_value": str(eh.get("new_value") if eh.get("new_value") is not None else clean_num(b.get("total_fees"))),
                        "edited_by_name": eh.get("edited_by_name") or eh.get("edited_by") or b.get("created_by") or "STAFF",
                        "edited_date": dt_s
                    })
                    by_source["Registration Billing"] += 1
                    
            # 2. Include all verified bills under proper billing source
            for b in res["bills"]:
                src = "Registration Billing"
                cat = b.get("category", "").upper()
                if "PHARM" in cat:
                    src = "Pharmacy Billing"
                elif "INVEST" in cat:
                    src = "Investigation Billing"
                elif "RETURN" in cat:
                    src = "Sales Return"
                else:
                    src = "Registration Billing"
                    
                by_source[src] = by_source.get(src, 0) + 1
                gross_amt = clean_num(b.get("gross") or b.get("total_amount") or b.get("amount") or 0.0)
                net_amt = clean_num(b.get("net_amount") or b.get("cash") or b.get("amount") or 0.0)
                old_val = str(round(gross_amt, 2)) if gross_amt != 0 else str(round(net_amt, 2))
                new_val = str(round(net_amt, 2))

                audit_rows.append({
                    "source": src,
                    "record_no": b.get("bill_no"),
                    "uhid": b.get("uhid") or b.get("mr_no") or "",
                    "patient_name": b.get("patient_name") or "Patient",
                    "description": f"Verified {b.get('payment_mode', 'CASH')} collection for {b.get('category')}",
                    "old_value": old_val,
                    "new_value": new_val,
                    "edited_by_name": b.get("cashier_name") or b.get("cashier_id") or "Counter Staff",
                    "edited_date": b.get("date")
                })
        finally:
            client.close()
            
        return Response({
            "success": True,
            "report_title": "Accounts Audit Report",
            "date_range": res["date_range"],
            "summary": {
                "count": len(audit_rows),
                "by_source": by_source,
                **res["financial_summary"]
            },
            "counts": res["counts"],
            "data": audit_rows
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def bill_wise_detailed_api(request):
    """
    Dedicated Bill Wise Detailed Report API.
    Itemized line-by-line revenue analysis per patient bill.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet"),
            shift_no=data.get("shiftno") or data.get("shift_no")
        )
        
        # Ingest and harmonize all bills, sales returns, and counter expense vouchers
        all_items = list(res["bills"])
        existing_bill_nos = set(str(b.get("bill_no") or "") for b in all_items)
        
        for ev in res.get("expense_vouchers", []):
            v_no = str(ev.get("voucher_no") or "").strip()
            if v_no and v_no not in existing_bill_nos and v_no != "—":
                amt = clean_num(ev.get("amount") or 0.0)
                all_items.append({
                    "bill_no": v_no,
                    "date": ev.get("date") or "",
                    "category": "EXPENSE PAYMENT",
                    "uhid": "—",
                    "mr_no": "—",
                    "ip_number": "—",
                    "patient_name": ev.get("description") or ev.get("account_head") or "Counter Expense Payment",
                    "gross": -amt,
                    "amount": amt,
                    "cash": -amt,
                    "card": 0.0,
                    "bank": 0.0,
                    "credit": 0.0,
                    "net_amount": -amt,
                    "payment_mode": "Cash",
                    "particulars": [{"itemName": ev.get("description") or "Counter Payment Voucher"}],
                    "shift_no": ev.get("shift_no") or "",
                    "cashier_id": ev.get("cashier_id") or "",
                    "cashier_name": ev.get("cashier_name") or "STAFF",
                    "is_expense": True,
                    "expense_amount": amt
                })

        # Flag sales returns and payments for frontend rendering
        tot_sales_returns = 0.0
        tot_expenses_paid = 0.0
        tot_gross_revenue = 0.0
        tot_cash_in = 0.0
        tot_card_in = 0.0
        tot_credit_in = 0.0

        for b in all_items:
            cat_l = str(b.get("category") or "").lower()
            amt = abs(clean_num(b.get("gross") or b.get("amount") or 0.0))
            is_sr = b.get("is_sales_return") or ("return" in cat_l) or ("refund" in cat_l) or (clean_num(b.get("sales_return")) > 0)
            is_exp = b.get("is_expense") or ("expense" in cat_l) or ("payment" in cat_l and "op" not in cat_l and "ip" not in cat_l)

            b["is_sales_return"] = is_sr
            b["is_expense"] = is_exp

            if is_sr:
                b["sales_return_amount"] = amt
                b["expense_amount"] = 0.0
                tot_sales_returns += amt
            elif is_exp:
                b["sales_return_amount"] = 0.0
                b["expense_amount"] = amt
                tot_expenses_paid += amt
            else:
                b["sales_return_amount"] = 0.0
                b["expense_amount"] = 0.0
                tot_gross_revenue += amt
                if clean_num(b.get("cash")) > 0:
                    tot_cash_in += clean_num(b.get("cash"))
                if clean_num(b.get("bank")) > 0:
                    tot_card_in += clean_num(b.get("bank"))
                if clean_num(b.get("credit")) > 0:
                    tot_credit_in += clean_num(b.get("credit"))

        # Sort by category then date
        sorted_bills = sorted(all_items, key=lambda x: (str(x.get("category") or ""), str(x.get("date") or ""), str(x.get("bill_no") or "")))
        
        net_rev = round(tot_gross_revenue - tot_sales_returns - tot_expenses_paid, 2)
        net_cash = round(tot_cash_in - tot_sales_returns - tot_expenses_paid, 2)

        return Response({
            "success": True,
            "report_title": "Bill Wise Detailed Report",
            "date_range": res["date_range"],
            "summary": {
                "total_collection": round(tot_gross_revenue, 2),
                "total_gross_revenue": round(tot_gross_revenue, 2),
                "total_cash": round(tot_cash_in, 2),
                "total_card": round(tot_card_in, 2),
                "total_credit": round(tot_credit_in, 2),
                "total_sales_returns": round(tot_sales_returns, 2),
                "sales_return_amount": round(tot_sales_returns, 2),
                "total_expenses_paid": round(tot_expenses_paid, 2),
                "counter_expenses_paid": round(tot_expenses_paid, 2),
                "expense_payment_amount": round(tot_expenses_paid, 2),
                "net_collection": net_rev,
                "net_revenue": net_rev,
                "net_cash_handover": net_cash,
                "count": len(sorted_bills)
            },
            "data": sorted_bills
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def miscellaneous_payment_api(request):
    """
    Dedicated Miscellaneous Payment Report API.
    Sundry receipts and counter expense payment vouchers.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        f_str = data.get("from_date") or data.get("start_date")
        t_str = data.get("to_date") or data.get("end_date")
        outlet_code = data.get("outlet_code") or data.get("outlet")
        
        from .core_ledger_engine import get_db, parse_date, format_dt
        from datetime import timedelta
        import json
        
        client, db, g_db = get_db()
        try:
            f_d = parse_date(f_str) if f_str else datetime.now().date()
            t_d = parse_date(t_str, is_end=True) if t_str else datetime.now()
            f_dt_utc = f_d - timedelta(hours=5, minutes=30)
            t_dt_utc = t_d - timedelta(hours=5, minutes=30)
            
            q = {"$or": [
                {"created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
                {"voucher_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}}
            ]}
            if outlet_code and str(outlet_code).lower() != "all":
                q["outlet_code"] = outlet_code
                
            docs = list(db["hospital_receiptandpayment"].find(q).sort("voucher_no", 1))
            
            # Cashier profile lookup
            cashier_map = {}
            try:
                prof_docs = list(g_db["backend_diagnostics_profile"].find({}, {"employeeId": 1, "employeeName": 1, "_id": 0}))
                cashier_map = {p["employeeId"]: p["employeeName"] for p in prof_docs if p.get("employeeId")}
            except Exception:
                pass
                
            vouchers = []
            for d in docs:
                r_type = str(d.get("receipt_type") or "Receipt").capitalize()
                v_type = "Payment" if "pay" in r_type.lower() else "Receipt"
                amt = clean_num(d.get("amount"))
                desc_str = str(d.get("description") or "")
                party_name = "-"
                narration = desc_str
                if desc_str.startswith("{"):
                    try:
                        p_data = json.loads(desc_str)
                        party_name = p_data.get("patient_name") or p_data.get("name") or "-"
                        narration = p_data.get("reason") or p_data.get("narration") or desc_str
                    except Exception:
                        pass
                        
                c_id = str(d.get("CashierID") or d.get("created_by") or "")
                c_name = cashier_map.get(c_id, c_id)
                v_date = d.get("voucher_date") or d.get("created_date")
                dt_str = format_ist_datetime(v_date) if v_date else ""
                
                vouchers.append({
                    "voucher_no": d.get("voucher_no") or str(d.get("_id"))[-8:],
                    "date": dt_str,
                    "voucher_type": v_type,
                    "account_head": str(d.get("account_head") or "Sundry"),
                    "paid_to_or_received_from": party_name,
                    "amount": amt,
                    "cashier_id": c_id,
                    "cashier_name": c_name,
                    "narration": narration
                })
                
            tot_receipts = round(sum(v["amount"] for v in vouchers if v["voucher_type"] == "Receipt"), 2)
            tot_payments = round(sum(v["amount"] for v in vouchers if v["voucher_type"] == "Payment"), 2)
            net_sundry = round(tot_receipts - tot_payments, 2)
            
            return Response({
                "success": True,
                "report_title": "Miscellaneous Payment Report",
                "date_range": {"from_date": str(f_d)[:10], "to_date": str(t_d)[:10]},
                "summary": {
                    "total_receipts": tot_receipts,
                    "total_payments": tot_payments,
                    "net_sundry_cash": net_sundry
                },
                "count": len(vouchers),
                "data": vouchers,
                "receipts": [v for v in vouchers if v["voucher_type"] == "Receipt"],
                "payments": [v for v in vouchers if v["voucher_type"] == "Payment"]
            }, status=status.HTTP_200_OK)
        finally:
            client.close()
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
