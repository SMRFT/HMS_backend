"""
Cluster 2: Digital Payments & Department Revenue APIs
=====================================================
1. Credit Card & Electronic Payment Report
2. Date-Wise Collection Summary
3. Department-Wise Collection Report
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from .core_ledger_engine import AccountsLedgerEngine, clean_num
from hospital.Views.AccountsReport.accounting_reports import date_wise_collection_summary_report

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def credit_card_report_api(request):
    """
    Dedicated Credit Card & Electronic Payment Report API.
    Itemized POS, Card, UPI, and Bank settlements matching EDC bank statements.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet"),
            shift_no=data.get("shiftno") or data.get("shift_no")
        )
        
        # Filter for digital/card payments
        card_bills = []
        for b in res["bills"]:
            if b["bank"] > 0:
                b["card_amount"] = b["bank"]
                b["card"] = b["bank"]
                b["amount"] = b["bank"]
                b["net_amount"] = b["bank"]
                b["mr_no"] = b.get("uhid") or "-"
                b["terminal_machine"] = b.get("outlet_code") or "Main POS"
                b["card_type"] = b.get("payment_mode") or "Credit/Debit Card"
                b["auth_code"] = "-"
                card_bills.append(b)
        
        # Group by category
        by_category = {}
        for b in card_bills:
            cat = b["category"]
            by_category.setdefault(cat, []).append(b)
            
        grouped_data = []
        for cat, items in by_category.items():
            tot = round(sum(it["bank"] for it in items), 2)
            grouped_data.append({
                "category": cat,
                "count": len(items),
                "total": tot,
                "items": items
            })
            
        return Response({
            "success": True,
            "report_title": "Credit Card & Electronic Payment Report",
            "date_range": res["date_range"],
            "summary": {
                **res["financial_summary"],
                "total_card_amount": res["financial_summary"]["card_and_bank_collections"],
                "total_transactions": len(card_bills)
            },
            "grouped_data": grouped_data,
            "data": card_bills
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def date_wise_collection_summary_api(request):
    """
    Dedicated Date-Wise Collection Summary API.
    Revenue matrix grouped by Date and Billing Head matching Shanmuga Hospital collection summary,
    powered natively by the Core Accounts Ledger Engine.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        from_d = data.get("from_date") or data.get("start_date")
        to_d = data.get("to_date") or data.get("end_date")
        outlet = data.get("outlet_code") or data.get("outlet")
        
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=from_d,
            to_str=to_d,
            outlet_code=outlet
        )
        
        summary_map = {}
        for b in res.get("bills", []):
            raw_d = str(b.get("date") or "")
            d_str = from_d or ""
            if "/" in raw_d:
                parts = raw_d.split(" ")[0].split("/")
                if len(parts) == 3:
                    d_str = f"{parts[2]}-{parts[1]}-{parts[0]}"
            elif len(raw_d) >= 10:
                d_str = raw_d[:10]
                
            cat = str(b.get("category") or "GENERAL").strip()
            b_no = str(b.get("bill_no") or "").strip()
            
            gross = clean_num(b.get("gross"))
            cash = clean_num(b.get("cash"))
            bank = clean_num(b.get("bank") or b.get("card"))
            credit = clean_num(b.get("credit"))
            net = clean_num(b.get("net_amount") or (cash + bank))
            
            disc = clean_num(b.get("discount"))
            bill_adv = clean_num(b.get("advance_adjustment") or b.get("advance_amount")) if cat == "DISCHARGE" else 0.0
            sales_ret = 0.0
            adv_refd = 0.0
            
            if cat in ["REFUND", "SALES RETURNS", "SALES RETURN"]:
                sales_ret = abs(cash) if cash < 0 else abs(gross)
                gross = 0.0
                net = -abs(sales_ret)
                cash = -abs(sales_ret)
                bank = 0.0
                cat = "SALES RETURNS"
            elif cat in ["EXPENSE PAYMENT", "MISCELLANEOUS EXPENSE"]:
                adv_refd = abs(cash) if cash < 0 else abs(gross)
                gross = 0.0
                net = -abs(adv_refd)
                cash = -abs(adv_refd)
                bank = 0.0
                cat = "MISCELLANEOUS EXPENSE"
                
            key = (d_str, cat)
            if key not in summary_map:
                summary_map[key] = {
                    "date": d_str,
                    "bill_name": cat,
                    "bill_nos": [],
                    "gross_amount": 0.0,
                    "discount": 0.0,
                    "bill_adv": 0.0,
                    "ip_return": 0.0,
                    "sales_ret": 0.0,
                    "ip_credit": 0.0,
                    "p_debit": 0.0,
                    "debit_col": 0.0,
                    "adv_refd": 0.0,
                    "net_amount": 0.0,
                    "cash": 0.0,
                    "bank": 0.0
                }
                
            row = summary_map[key]
            if b_no: row["bill_nos"].append(b_no)
            row["gross_amount"] += gross
            row["discount"] += disc
            row["bill_adv"] += bill_adv
            row["sales_ret"] += sales_ret
            row["ip_credit"] += credit
            row["adv_refd"] += adv_refd
            row["net_amount"] += net
            row["cash"] += cash
            row["bank"] += bank

        rows = []
        for (d_str, cat), row in sorted(summary_map.items()):
            nos = row.pop("bill_nos")
            if nos:
                nos.sort()
                row["bill_range"] = f"{nos[0]}To{nos[-1]}"
            else:
                row["bill_range"] = ""
            for k in ["gross_amount", "discount", "bill_adv", "ip_return", "sales_ret", "ip_credit", "p_debit", "debit_col", "adv_refd", "net_amount", "cash", "bank"]:
                row[k] = round(row[k], 2)
            rows.append(row)

        categories = sorted(list(set(r.get("bill_name") for r in rows if r.get("bill_name"))))
        tot_gross = round(sum(r["gross_amount"] for r in rows), 2)
        tot_disc = round(sum(r["discount"] for r in rows), 2)
        tot_adv = round(sum(r["bill_adv"] for r in rows), 2)
        tot_ret = round(sum(r["sales_ret"] for r in rows), 2)
        tot_credit = round(sum(r["ip_credit"] for r in rows), 2)
        tot_refd = round(sum(r["adv_refd"] for r in rows), 2)
        tot_net = round(sum(r["net_amount"] for r in rows), 2)
        tot_cash = round(sum(r["cash"] for r in rows), 2)
        tot_bank = round(sum(r["bank"] for r in rows), 2)
        
        # Gross cash collected before expense deductions and refunds
        gross_cash = round(sum(r["cash"] for r in rows if r["cash"] > 0), 2)

        return Response({
            "success": True,
            "report_title": "Date-Wise Collection Summary",
            "date_range": res.get("date_range"),
            "outlet": outlet or "All Outlets",
            "categories": categories,
            "financial_summary": {
                **res.get("financial_summary", {}),
                "gross_cash": gross_cash,
                "expenses_paid": tot_refd,
                "sales_return": tot_ret,
                "closing_cash": tot_cash,
                "card_and_bank": tot_bank,
                "credit_tpa": tot_credit,
                "total_collection": round(gross_cash + tot_bank, 2)
            },
            "summary": {
                "total_gross": tot_gross,
                "total_discount": tot_disc,
                "total_bill_adv": tot_adv,
                "total_sales_ret": tot_ret,
                "total_credit": tot_credit,
                "total_adv_refd": tot_refd,
                "total_net": tot_net,
                "total_cash": tot_cash,
                "total_bank": tot_bank,
                "grand_total": tot_net
            },
            "data": rows
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def department_wise_collection_api(request):
    """
    Dedicated Department-Wise Collection API.
    Revenue grouped by clinical and store departments.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet")
        )
        
        dept_map = {}
        for b in res["bills"]:
            cat = b["category"]
            dept_map.setdefault(cat, {
                "department": cat,
                "cash": 0.0,
                "card": 0.0,
                "credit": 0.0,
                "total_revenue": 0.0,
                "bill_count": 0
            })
            dept_map[cat]["cash"] += b["cash"]
            dept_map[cat]["card"] += b["bank"]
            dept_map[cat]["credit"] += b["credit"]
            dept_map[cat]["total_revenue"] += b["gross"]
            dept_map[cat]["bill_count"] += 1
            
        rows = list(dept_map.values())
        for r in rows:
            r["bills_count"] = r["bill_count"]
            r["cash"] = round(r["cash"], 2)
            r["card"] = round(r["card"], 2)
            r["credit"] = round(r["credit"], 2)
            r["total_revenue"] = round(r["total_revenue"], 2)
            r["total"] = r["total_revenue"]
            
        rows.sort(key=lambda x: -x["total_revenue"])
        
        tot_cash = round(sum(r["cash"] for r in rows), 2)
        tot_card = round(sum(r["card"] for r in rows), 2)
        tot_credit = round(sum(r["credit"] for r in rows), 2)
        tot_rev = round(sum(r["total"] for r in rows), 2)

        return Response({
            "success": True,
            "report_title": "Department-Wise Collection Report",
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
