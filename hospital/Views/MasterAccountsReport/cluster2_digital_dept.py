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
    Itemized POS, Card, UPI, and Bank settlements grouped by Date and Category,
    matching Shanmuga Hospital official format with 100% Shift Basis tally.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        is_refresh = str(data.get("refresh") or data.get("force_refresh") or "").lower() in ["true", "1"]
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet"),
            shift_no=data.get("shiftno") or data.get("shift_no"),
            force_refresh=is_refresh
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

        # Extract and normalize card/bank bills
        card_type_param = str(data.get("card_type") or data.get("cardType") or "").strip().lower()
        card_machine_param = str(data.get("card_machine") or data.get("cardMachine") or "").strip().lower()

        normalized_bills = []
        for b in res["bills"]:
            if b.get("bank", 0) > 0:
                sort_key, d_disp = _parse_date_keys(b.get("date"))
                uhid_val = str(b.get("uhid") or b.get("mr_no") or "").strip()
                ip_val = str(b.get("ip_number") or "").strip()
                if ip_val == uhid_val:
                    ip_val = ""
                amt = round(float(b.get("bank", 0)), 2)

                p_mode = str(b.get("payment_mode") or "").strip().upper()
                card_type = b.get("card_type")
                if not card_type:
                    if any(k in p_mode for k in ["UPI", "GPAY", "GOOGLE", "PHONEPE", "PAYTM", "BHIM", "QR"]):
                        card_type = "UPI"
                    elif "RUPAY" in p_mode:
                        card_type = "RUPAY CARD"
                    elif "VISA" in p_mode:
                        card_type = "VISA CARD"
                    elif "MASTER" in p_mode:
                        card_type = "MASTER CARD"
                    elif "DEBIT" in p_mode:
                        card_type = "DEBIT CARD"
                    elif "CREDIT" in p_mode:
                        card_type = "CREDIT CARD"
                    else:
                        card_type = "CARD"
                else:
                    card_type = str(card_type).upper()

                # Card machine resolution
                card_machine = b.get("card_machine")
                if not card_machine or card_machine == "POS":
                    pd = b.get("payment_details") or {}
                    if isinstance(pd, str):
                        try:
                            pd = json.loads(pd)
                        except Exception:
                            pd = {}
                    found_mach = (
                        pd.get("Card Machine") or pd.get("card_machine") or pd.get("cardMachine") or
                        pd.get("pos_machine") or pd.get("machine_name") or pd.get("machine") or
                        pd.get("pos") or pd.get("terminal") or pd.get("terminal_machine") or ""
                    )
                    if not found_mach and isinstance(pd.get("breakdown"), list):
                        for item in pd["breakdown"]:
                            if isinstance(item, dict):
                                found_mach = (
                                    item.get("Card Machine") or item.get("card_machine") or item.get("cardMachine") or
                                    item.get("pos_machine") or item.get("machine_name") or item.get("machine") or
                                    item.get("pos") or item.get("terminal") or item.get("terminal_machine") or ""
                                )
                                if found_mach:
                                    break
                    if found_mach:
                        card_machine = str(found_mach).strip()
                    elif not card_machine:
                        if "PAYTM" in p_mode: card_machine = "Paytm"
                        elif "BAJAJ" in p_mode: card_machine = "Bajaj"
                        elif "360" in p_mode: card_machine = "360 POS"
                        elif "PNB" in p_mode: card_machine = "PNB"
                        elif any(k in p_mode for k in ["UPI", "GPAY", "GOOGLE", "PHONEPE", "BHIM", "QR"]): card_machine = "UPI"
                        else: card_machine = "POS"

                card_number = b.get("card_number") or ""
                if not card_number:
                    pd = b.get("payment_details") or {}
                    if isinstance(pd, str):
                        try:
                            pd = json.loads(pd)
                        except Exception:
                            pd = {}
                    card_number = str(pd.get("card_number") or pd.get("cardNumber") or pd.get("card_no") or "").strip()
                    if not card_number and isinstance(pd.get("breakdown"), list):
                        for item in pd["breakdown"]:
                            if isinstance(item, dict):
                                c_n = str(item.get("card_number") or item.get("cardNumber") or item.get("card_no") or "").strip()
                                if c_n:
                                    card_number = c_n
                                    break
                if not card_number:
                    card_number = card_machine

                # Apply card_type or card_machine filter if supplied via query params
                if card_type_param and card_type_param != "all":
                    if card_type.lower() != card_type_param and card_type_param not in card_type.lower():
                        continue
                if card_machine_param and card_machine_param != "all":
                    if card_machine.lower() != card_machine_param and card_machine_param not in card_machine.lower():
                        continue
                
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
                    "card_type": card_type,
                    "card_machine": card_machine,
                    "card_number": card_number,
                    "amount": amt,
                    "card_amount": amt,
                    "bank": amt,
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

        machine_summary = {}
        for r in flat_rows_with_slno:
            m_key = r.get("card_machine") or r.get("card_number") or r.get("card_type") or "Main POS"
            machine_summary[m_key] = round(machine_summary.get(m_key, 0.0) + r["amount"], 2)

        distinct_card_types = sorted(list({r["card_type"] for r in flat_rows_with_slno if r.get("card_type")}))
        distinct_card_machines = sorted(list({r["card_machine"] for r in flat_rows_with_slno if r.get("card_machine")}))

        summary = {
            **res["financial_summary"],
            "total_transactions": len(flat_rows_with_slno),
            "total_amount": grand_total,
            "total_card_collection": grand_total,
            "total_card_amount": grand_total,
            "by_category": by_category_summary,
            "by_machine": machine_summary,
            "card_types": distinct_card_types,
            "card_machines": distinct_card_machines
        }

        return Response({
            "success": True,
            "report_title": "Credit Card & Electronic Payment Report",
            "date_range": res["date_range"],
            "financial_summary": res["financial_summary"],
            "grouped_data": grouped_result,
            "data": flat_rows_with_slno,
            "summary": summary,
            "grand_total": grand_total,
            "category_summary": by_category_summary,
            "machine_summary": machine_summary
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
        
        is_refresh = str(data.get("refresh") or data.get("force_refresh") or "").lower() in ["true", "1"]
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=from_d,
            to_str=to_d,
            outlet_code=outlet,
            force_refresh=is_refresh
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
            if cat.upper() in ["DISCHARGE", "DISCHARGEBILLS"]:
                cat = "DISCHARGE"
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
            
            cat_upper = cat.upper()
            if any(k in cat_upper for k in ["REFUND", "RETURN"]):
                sales_ret = abs(cash) if cash < 0 else abs(gross)
                gross = 0.0
                net = -abs(sales_ret)
                p_m = str(b.get("payment_mode") or b.get("payment_type") or "").strip().lower()
                if any(term in p_m for term in ["bank", "card", "online", "pos", "upi", "neft", "rtgs"]):
                    bank = -abs(sales_ret)
                    cash = 0.0
                else:
                    cash = -abs(sales_ret)
                    bank = 0.0
                credit = 0.0
                cat = "SALES RETURNS"
            elif any(k in cat_upper for k in ["EXPENSE", "PAYMENT"]):
                adv_refd = abs(cash) if cash < 0 else abs(gross)
                gross = 0.0
                net = -abs(adv_refd)
                p_m = str(b.get("payment_mode") or b.get("payment_type") or "").strip().lower()
                if any(term in p_m for term in ["bank", "card", "online", "pos", "upi", "neft", "rtgs"]):
                    bank = -abs(adv_refd)
                    cash = 0.0
                else:
                    cash = -abs(adv_refd)
                    bank = 0.0
                credit = 0.0
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
            row["card"] = row["bank"]
            row["total"] = row["net_amount"]
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
def bill_type_wise_collection_api(request):
    """
    Dedicated Bill Type-Wise Collection API.
    Revenue grouped by hospital billing heads (Pharmacy, Lab, Scan, Registration, Advance, Discharge).
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        cat_filter = (data.get("category") or data.get("bill_type") or "").strip()

        is_refresh = str(data.get("refresh") or data.get("force_refresh") or "").lower() in ["true", "1"]
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet"),
            force_refresh=is_refresh
        )
        
        dept_map = {}
        for b in res["bills"]:
            cat = b["category"]
            if cat_filter and cat_filter.lower() not in ["all", "all types", "all categories", ""]:
                cat_f_lower = cat_filter.strip().lower()
                cat_lower = cat.strip().lower()
                # Flexible matching for cardiology and package breakdowns
                if cat_f_lower == "cardiology" or "cardio" in cat_f_lower:
                    if "cardio" not in cat_lower and not any(k in cat_lower for k in ["ecg", "echo", "tmt", "holter"]):
                        continue
                elif cat_f_lower == "package" or "package" in cat_f_lower:
                    if "package" not in cat_lower:
                        continue
                elif cat_lower != cat_f_lower and cat_f_lower not in cat_lower:
                    continue
            dept_map.setdefault(cat, {
                "bill_type": cat,
                "category": cat,
                "department": cat,
                "cash": 0.0,
                "card": 0.0,
                "credit": 0.0,
                "total_revenue": 0.0,
                "bill_count": 0
            })
            c_val = b["cash"] if b["cash"] > 0 else 0.0
            b_val = b["bank"] if b["bank"] > 0 else 0.0
            cr_val = b["credit"] if b["credit"] > 0 else 0.0
            dept_map[cat]["cash"] += c_val
            dept_map[cat]["card"] += b_val
            dept_map[cat]["credit"] += cr_val
            dept_map[cat]["bill_count"] += 1
            
        rows = list(dept_map.values())
        for r in rows:
            r["bills_count"] = r["bill_count"]
            r["cash"] = round(r["cash"], 2)
            r["card"] = round(r["card"], 2)
            r["credit"] = round(r["credit"], 2)
            r["total_revenue"] = round(r["cash"] + r["card"] + r["credit"], 2)
            r["total"] = r["total_revenue"]
            
        rows.sort(key=lambda x: -x["total_revenue"])
        
        tot_cash = round(sum(r["cash"] for r in rows), 2)
        tot_card = round(sum(r["card"] for r in rows), 2)
        tot_credit = round(sum(r["credit"] for r in rows), 2)
        tot_rev = round(tot_cash + tot_card + tot_credit, 2)

        return Response({
            "success": True,
            "report_title": "Bill Type-Wise Collection Report",
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

department_wise_collection_api = bill_type_wise_collection_api
