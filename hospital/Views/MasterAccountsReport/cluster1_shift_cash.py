"""
Cluster 1: Counter Cash & Shift Reconciliation APIs
===================================================
1. Shift Basis Collection Report
2. Cash Bills Summary Report
3. Daily Cash Collection Report
4. Cashier-Wise Collection Summary
5. Cashier-Wise Detailed Collection
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from .core_ledger_engine import AccountsLedgerEngine, clean_num, format_dt, format_ist_time, format_ist_date, format_ist_datetime, to_ist

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def shift_basis_collection_api(request):
    """
    Dedicated Shift Basis Collection Report API.
    Returns cashier shifts with gross cash, expense payments, net cash handed over,
    and verified status matching physical cashier handover.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet"),
            shift_no=data.get("shiftno") or data.get("shift_no")
        )
        # Format summary_data matching ShiftBasisReport.js expectations
        summary_data = []
        for s in res["shift_reconciliation"]:
            dt_s = s.get("date") or res["date_range"]["from_date"]
            c_val = s.get("gross_cash") or 0.0
            cr_val = s.get("credit_collection") or 0.0
            cd_val = s.get("card_collection") or 0.0
            ret_val = s.get("sales_return") or 0.0
            tot_val = round(c_val + cr_val + cd_val, 2)
            open_bal = s.get("opening_balance") or 0.0
            close_bal = s.get("closing_balance") or s.get("net_handover_cash") or 0.0
            summary_data.append({
                "shiftno": s["shift_no"],
                "date": dt_s,
                "displayDate": dt_s,
                "SelectedOutlet": s.get("outlet_code") or "OLET003",
                "User": s["cashier_name"],
                "CashierID": s["cashier_id"],
                "StartTime": format_ist_time(s.get("start_time") or s.get("StartTime") or s.get("StartingTime")) or "08:00 AM",
                "EndTime": format_ist_time(s.get("end_time") or s.get("EndTime") or s.get("closingTime")) if (s.get("end_time") or s.get("EndTime") or s.get("closingTime")) else "Active",
                "openBal": open_bal,
                "cashColl": c_val,
                "creditColl": cr_val,
                "cardColl": cd_val,
                "totalColl": tot_val,
                "expensesPaid": s.get("expenses_paid") or 0.0,
                "expenses_paid": s.get("expenses_paid") or 0.0,
                "netHandover": s.get("net_handover_cash") or close_bal,
                "net_handover_cash": s.get("net_handover_cash") or close_bal,
                "sales_return": ret_val,
                "retAmt": ret_val,
                "closeBal": close_bal,
                "ShiftStatus": s.get("shift_status") or "closed",
                **s
            })

        return Response({
            "success": True,
            "report_title": "Shift Basis Collection Report",
            "date_range": res["date_range"],
            "summary": res["financial_summary"],
            "summary_data": summary_data,
            "data": summary_data,
            "shift_reconciliation": res["shift_reconciliation"],
            "bills": res["bills"],
            "itemized_bills": res["bills"],
            "expense_deductions": res["expense_vouchers"]
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def cash_bills_summary_api(request):
    """
    Dedicated Cash Bills Summary Report API.
    Categorizes cash bills by billing heads grouped by Date and Category,
    matching Shanmuga Hospital official format with 100% Shift Basis tally.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet"),
            shift_no=data.get("shiftno") or data.get("shift_no")
        )
        
        def _parse_date_keys(raw_d):
            raw_s = str(raw_d or '')
            parts = raw_s[:10].split('/')
            if len(parts) == 3 and len(parts[2]) == 4:
                return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}", f"{parts[0].zfill(2)}/{parts[1].zfill(2)}/{parts[2]}"
            parts_dash = raw_s[:10].split('-')
            if len(parts_dash) == 3 and len(parts_dash[0]) == 4:
                return raw_s[:10], f"{parts_dash[2]}/{parts_dash[1]}/{parts_dash[0]}"
            return raw_s[:10], raw_s[:10]

        # Extract and normalize cash bills
        normalized_bills = []
        for b in res["bills"]:
            if b.get("cash", 0) > 0:
                sort_key, d_disp = _parse_date_keys(b.get("date"))
                uhid_val = str(b.get("uhid") or b.get("mr_no") or "").strip()
                ip_val = str(b.get("ip_number") or "").strip()
                if ip_val == uhid_val:
                    ip_val = ""
                amt = round(float(b.get("cash", 0)), 2)
                
                normalized_bills.append({
                    **b,
                    "date": sort_key,
                    "date_display": d_disp,
                    "category": b.get("category") or "OTHER",
                    "bill_no": b.get("bill_no") or "-",
                    "mr_no": uhid_val if uhid_val else "-",
                    "uhid": uhid_val,
                    "ip_number": ip_val,
                    "patient_name": b.get("patient_name") or "General / Cash Patient",
                    "payment_mode": "CASH",
                    "amount": amt,
                    "cash": amt,
                    "user": (b.get("cashier_name") or b.get("user") or "STAFF").upper(),
                    "_sort_key": sort_key
                })

        # Sort all rows by (date asc, category asc, bill_no asc)
        normalized_bills.sort(key=lambda x: (x["_sort_key"], x["category"], str(x["bill_no"])))

        # Build hierarchical structure: Date -> Category (Sections) -> Items
        date_groups = {}
        for b in normalized_bills:
            d_key = b["_sort_key"]
            d_disp = b["date_display"]
            cat = b["category"]
            
            if d_key not in date_groups:
                date_groups[d_key] = {
                    "date": d_key,
                    "date_display": d_disp,
                    "sections": {},
                    "date_total": 0.0,
                    "count": 0
                }
            dg = date_groups[d_key]
            if cat not in dg["sections"]:
                dg["sections"][cat] = {
                    "category": cat,
                    "items": [],
                    "total": 0.0,
                    "count": 0
                }
            sec = dg["sections"][cat]
            sec["items"].append(b)
            sec["total"] += b["amount"]
            sec["count"] += 1
            dg["date_total"] += b["amount"]
            dg["count"] += 1

        grouped_result = []
        flat_rows_with_slno = []
        global_slno = 1

        for d_key in sorted(date_groups.keys()):
            dg = date_groups[d_key]
            sec_list = []
            for cat_name in sorted(dg["sections"].keys()):
                sec_obj = dg["sections"][cat_name]
                for item in sec_obj["items"]:
                    item_clean = {k: v for k, v in item.items() if k != "_sort_key"}
                    item_clean["slno"] = global_slno
                    item_clean["displaySlno"] = global_slno
                    global_slno += 1
                    flat_rows_with_slno.append(item_clean)
                sec_list.append({
                    "category": sec_obj["category"],
                    "items": sec_obj["items"],
                    "total": round(sec_obj["total"], 2),
                    "count": sec_obj["count"]
                })
            grouped_result.append({
                "date": dg["date"],
                "date_display": dg["date_display"],
                "sections": sec_list,
                "date_total": round(dg["date_total"], 2),
                "count": dg["count"]
            })

        grand_total = round(sum(r["amount"] for r in flat_rows_with_slno), 2)
        by_category_summary = {}
        for r in flat_rows_with_slno:
            by_category_summary[r["category"]] = round(by_category_summary.get(r["category"], 0.0) + r["amount"], 2)

        summary = {
            **res["financial_summary"],
            "total_transactions": len(flat_rows_with_slno),
            "total_amount": grand_total,
            "total_cash_bills": grand_total,
            "total_expenses": res["financial_summary"].get("counter_expenses_paid", 0.0),
            "net_cash_receipts": res["financial_summary"].get("net_cash_handover", 0.0),
            "total_bills_count": len(flat_rows_with_slno),
            "by_category": by_category_summary
        }

        return Response({
            "success": True,
            "report_title": "Cash Bills Summary Report",
            "date_range": res["date_range"],
            "financial_summary": res["financial_summary"],
            "grouped_data": grouped_result,
            "data": flat_rows_with_slno,
            "summary": summary,
            "grand_total": grand_total,
            "category_summary": by_category_summary,
            "expense_vouchers": res["expense_vouchers"],
            "total_cash": grand_total,
            "net_handover_cash": res["financial_summary"].get("net_cash_handover", 0.0)
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def daily_cash_report_api(request):
    """
    Dedicated Daily Cash Report API.
    Consolidated day-by-day cash intake and expense payments across the entire hospital.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet")
        )
        
        # Group cash flow day by day
        day_map = {}
        for b in res["bills"]:
            dt_str = b["date"][:10]
            if not dt_str:
                continue
            day_map.setdefault(dt_str, {
                "date": dt_str,
                "opening_balance": 0.0,
                "op_cash": 0.0,
                "ip_advance_cash": 0.0,
                "discharge_cash": 0.0,
                "pharmacy_cash": 0.0,
                "misc_cash": 0.0,
                "total_inflow": 0.0,
                "expenses_paid": 0.0,
                "sales_return": 0.0,
                "closing_balance": 0.0,
                "cash_in": 0.0,
                "cash_out": 0.0,
                "by_category": {}
            })

            # Check if this bill is a sales return or refund
            if b.get("is_sales_return") or b.get("category") == "Sales Return" or b.get("sales_return", 0) > 0 or b.get("return_amount", 0) > 0:
                ret_val = clean_num(b.get("return_amount") or b.get("sales_return") or b.get("amount") or abs(b.get("cash", 0)))
                day_map[dt_str]["sales_return"] += ret_val
            elif b.get("is_refund") or b.get("category") == "REFUND" or b.get("refund_amount", 0) > 0:
                ref_val = clean_num(b.get("refund_amount") or b.get("amount") or abs(b.get("cash", 0)))
                day_map[dt_str]["sales_return"] += ref_val
            elif b["cash"] > 0:
                amt = b["cash"]
                cat = b.get("category", "").upper()
                day_map[dt_str]["cash_in"] += amt
                day_map[dt_str]["total_inflow"] += amt
                day_map[dt_str]["by_category"][cat] = day_map[dt_str]["by_category"].get(cat, 0.0) + amt
                
                if "ADVANCE" in cat:
                    day_map[dt_str]["ip_advance_cash"] += amt
                elif "DISCHARGE" in cat:
                    day_map[dt_str]["discharge_cash"] += amt
                elif "PHARMACY" in cat:
                    day_map[dt_str]["pharmacy_cash"] += amt
                elif "MISCELLANEOUS" in cat:
                    day_map[dt_str]["misc_cash"] += amt
                else:
                    day_map[dt_str]["op_cash"] += amt
                
        for v in res["expense_vouchers"]:
            dt_str = v["date"][:10]
            if not dt_str:
                continue
            day_map.setdefault(dt_str, {
                "date": dt_str,
                "opening_balance": 0.0,
                "op_cash": 0.0,
                "ip_advance_cash": 0.0,
                "discharge_cash": 0.0,
                "pharmacy_cash": 0.0,
                "misc_cash": 0.0,
                "total_inflow": 0.0,
                "expenses_paid": 0.0,
                "sales_return": 0.0,
                "closing_balance": 0.0,
                "cash_in": 0.0,
                "cash_out": 0.0,
                "by_category": {}
            })
            day_map[dt_str]["expenses_paid"] += v["amount"]

        # Tally with shift-level resolved sales returns per date
        date_shift_returns = {}
        for s in res.get("shift_reconciliation", []):
            s_dt = s.get("date") or ""
            if s_dt:
                date_shift_returns[s_dt] = date_shift_returns.get(s_dt, 0.0) + clean_num(s.get("sales_return"))

        for dt_str, day_row in day_map.items():
            if dt_str in date_shift_returns:
                day_row["sales_return"] = max(day_row["sales_return"], date_shift_returns[dt_str])
            
        rows = sorted(day_map.values(), key=lambda x: x["date"])
        for r in rows:
            r["op_cash"] = round(r["op_cash"], 2)
            r["ip_advance_cash"] = round(r["ip_advance_cash"], 2)
            r["discharge_cash"] = round(r["discharge_cash"], 2)
            r["pharmacy_cash"] = round(r["pharmacy_cash"], 2)
            r["misc_cash"] = round(r["misc_cash"], 2)
            r["total_inflow"] = round(r["total_inflow"], 2)
            r["cash_in"] = r["total_inflow"]
            r["expenses_paid"] = round(r["expenses_paid"], 2)
            r["sales_return"] = round(r["sales_return"], 2)
            r["cash_out"] = round(r["expenses_paid"] + r["sales_return"], 2)
            r["closing_balance"] = round(r["total_inflow"] - r["expenses_paid"] - r["sales_return"], 2)
            r["net_cash"] = r["closing_balance"]

        tot_in = round(sum(r["total_inflow"] for r in rows), 2)
        tot_expenses = round(sum(r["expenses_paid"] for r in rows), 2)
        tot_returns = round(sum(r["sales_return"] for r in rows), 2)
        tot_out = round(tot_expenses + tot_returns, 2)
        tot_net = round(tot_in - tot_out, 2)

        return Response({
            "success": True,
            "report_title": "Daily Cash Collection Report",
            "date_range": res["date_range"],
            "summary": {
                "total_cash_in": tot_in,
                "total_expenses": tot_expenses,
                "total_sales_return": tot_returns,
                "total_cash_out": tot_out,
                "total_closing": tot_net,
                "net_cash_balance": tot_net
            },
            "data": rows
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def cashier_wise_summary_api(request):
    """
    Dedicated Cashier-Wise Collection Summary API.
    Aggregates cash, card, and credit collections by cashier with voucher deductions.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet")
        )
        
        cashier_map = {}
        for b in res["bills"]:
            cid = b["cashier_id"]
            # Extract date key from bill date field (format: "DD/MM/YYYY HH:MM AM" or ISO string)
            raw_date = str(b.get("date") or "")
            if raw_date:
                # Try "DD/MM/YYYY ..." format first
                parts = raw_date[:10].split("/")
                if len(parts) == 3 and len(parts[2]) == 4:
                    # DD/MM/YYYY - keep as-is for display
                    date_key = raw_date[:10]
                else:
                    # ISO format YYYY-MM-DD
                    date_key = raw_date[:10]
            else:
                date_key = "Unknown"
            key = (date_key, cid)
            cashier_map.setdefault(key, {
                "date": date_key,
                "cashier_id": cid,
                "cashier_name": b["cashier_name"],
                "gross_cash": 0.0,
                "expenses_paid": 0.0,
                "net_cash": 0.0,
                "card_amount": 0.0,
                "credit_amount": 0.0,
                "total_revenue": 0.0,
                "bill_count": 0
            })
            cashier_map[key]["gross_cash"] += b["cash"]
            cashier_map[key]["card_amount"] += b["bank"]
            cashier_map[key]["credit_amount"] += b["credit"]
            cashier_map[key]["total_revenue"] += b["gross"]
            cashier_map[key]["bill_count"] += 1
            
        for v in res["expense_vouchers"]:
            cid = v["cashier_id"]
            raw_vdate = str(v.get("date") or "")
            if raw_vdate:
                parts = raw_vdate[:10].split("/")
                if len(parts) == 3 and len(parts[2]) == 4:
                    v_date_key = raw_vdate[:10]
                else:
                    v_date_key = raw_vdate[:10]
            else:
                v_date_key = "Unknown"
            key = (v_date_key, cid)
            # Also try matching without date (fallback for mismatched dates)
            if key in cashier_map:
                cashier_map[key]["expenses_paid"] += v["amount"]
            else:
                # Fallback: match any entry for this cashier
                for k in cashier_map:
                    if k[1] == cid:
                        cashier_map[k]["expenses_paid"] += v["amount"]
                        break
                        
        def _sort_date_key(dk):
            """Convert DD/MM/YYYY or YYYY-MM-DD to sortable YYYY-MM-DD string."""
            parts = str(dk).split("/")
            if len(parts) == 3:
                return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
            return str(dk)
            
        rows = []
        for key in sorted(cashier_map.keys(), key=lambda k: (_sort_date_key(k[0]), str(k[1]))):
            r = cashier_map[key]
            cid = r["cashier_id"]
            b_date = r["date"]
            # Count distinct shifts for this cashier on this date
            shifts_seen = set(
                b.get("shift_no") for b in res["bills"]
                if b["cashier_id"] == cid and b.get("shift_no") and str(b.get("date") or "")[:10] == b_date
            )
            r["shifts_count"] = len(shifts_seen) if shifts_seen else 1
            r["gross_cash"] = round(r["gross_cash"], 2)
            r["cash"] = r["gross_cash"]
            r["expenses_paid"] = round(r["expenses_paid"], 2)
            r["net_cash"] = round(r["gross_cash"] - r["expenses_paid"], 2)
            r["card_amount"] = round(r["card_amount"], 2)
            r["card"] = r["card_amount"]
            r["credit_amount"] = round(r["credit_amount"], 2)
            r["credit"] = r["credit_amount"]
            r["total_revenue"] = round(r["cash"] + r["card"] + r["credit"], 2)
            r["total"] = r["total_revenue"]
            rows.append(r)
            
        tot_cash = round(sum(r["cash"] for r in rows), 2)
        tot_card = round(sum(r["card"] for r in rows), 2)
        tot_credit = round(sum(r["credit"] for r in rows), 2)
        tot_rev = round(sum(r["total"] for r in rows), 2)

        return Response({
            "success": True,
            "report_title": "Cashier-Wise Collection Summary",
            "date_range": res["date_range"],
            "summary": {
                **res["financial_summary"],
                "total_cash": tot_cash,
                "total_card": tot_card,
                "total_credit": tot_credit,
                "grand_total": tot_rev
            },
            "data": rows
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def cashier_wise_detailed_api(request):
    """
    Dedicated Cashier-Wise Detailed Collection API.
    Itemized bill-by-bill audit per cashier.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        cashier_id = data.get("cashier_id") or data.get("CashierID")
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet"),
            shift_no=data.get("shiftno") or data.get("shift_no")
        )
        
        bills = res["bills"]
        if cashier_id and str(cashier_id).lower() != "all":
            bills = [b for b in bills if b["cashier_id"] == str(cashier_id)]
            
        return Response({
            "success": True,
            "report_title": "Cashier-Wise Detailed Collection",
            "date_range": res["date_range"],
            "summary": res["financial_summary"],
            "data": bills
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
