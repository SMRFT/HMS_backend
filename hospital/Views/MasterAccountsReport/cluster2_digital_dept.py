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
from .core_ledger_engine import (
    AccountsLedgerEngine,
    clean_num,
    get_db,
    parse_date,
    to_ist,
    extract_card_metadata,
)
from hospital.Views.AccountsReport.accounting_reports import date_wise_collection_summary_report
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import time as _time

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


# ─────────────────────────────────────────────────────────────────────────────
# 4. Doctor Revenue Report (Date Wise Bills Analysis Detailed)
# ─────────────────────────────────────────────────────────────────────────────
_DOC_REV_CACHE = {
    "grn_batch_cost": {},
    "grn_item_cost": {},
    "grn_expires_at": 0.0,
    "doctor_map": {},
    "doctor_expires_at": 0.0,
}


def _get_grn_cost_maps(db, force_refresh=False):
    now_ts = _time.time()
    if not force_refresh and _DOC_REV_CACHE["grn_expires_at"] > now_ts and _DOC_REV_CACHE["grn_item_cost"]:
        return _DOC_REV_CACHE["grn_batch_cost"], _DOC_REV_CACHE["grn_item_cost"]

    batch_map = {}
    item_map = {}
    existing_cols = set(db.list_collection_names())
    for col_name in ("hospital_grn", "hospital_opgrn"):
        if col_name not in existing_cols:
            continue
        cursor = db[col_name].find({"is_active": {"$ne": False}}, {"items": 1, "date": 1}).sort("date", 1)
        for g in cursor:
            raw_items = g.get("items")
            if isinstance(raw_items, str):
                try:
                    items = json.loads(raw_items)
                except Exception:
                    continue
            elif isinstance(raw_items, list):
                items = raw_items
            else:
                continue

            for it in items:
                if not isinstance(it, dict):
                    continue
                iid = str(it.get("item_id") or "").strip()
                if not iid:
                    continue
                batch = str(it.get("batch") or it.get("batch_number") or "").strip().upper()
                tot_stock = clean_num(it.get("total_stock") or it.get("quantity"))
                p_cost = clean_num(it.get("purchase_cost"))
                if p_cost > 0 and tot_stock > 0:
                    unit_cost = p_cost / tot_stock
                else:
                    unit_cost = clean_num(it.get("unit_price") or it.get("purchase_cost_display"))
                if unit_cost > 0:
                    if batch:
                        batch_map[(iid, batch)] = unit_cost
                    item_map[iid] = unit_cost

    _DOC_REV_CACHE["grn_batch_cost"] = batch_map
    _DOC_REV_CACHE["grn_item_cost"] = item_map
    _DOC_REV_CACHE["grn_expires_at"] = now_ts + 900.0
    return batch_map, item_map


def _get_doctor_map(g_db, force_refresh=False):
    now_ts = _time.time()
    if not force_refresh and _DOC_REV_CACHE["doctor_expires_at"] > now_ts and _DOC_REV_CACHE["doctor_map"]:
        return _DOC_REV_CACHE["doctor_map"]

    mapping = {}
    for p in g_db["backend_diagnostics_profile"].find(
        {}, {"employeeId": 1, "employeeName": 1, "firstName": 1, "lastName": 1, "name": 1, "_id": 0}
    ):
        emp_id = str(p.get("employeeId") or "").strip()
        name = str(
            p.get("employeeName")
            or p.get("name")
            or f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
            or ""
        ).strip()
        if emp_id and name:
            mapping[emp_id] = name
            mapping[emp_id.upper()] = name
            if emp_id.isdigit():
                mapping[str(int(emp_id))] = name

    _DOC_REV_CACHE["doctor_map"] = mapping
    _DOC_REV_CACHE["doctor_expires_at"] = now_ts + 900.0
    return mapping


def _resolve_doc_name(raw_doc, doctor_map, fallback_name=""):
    d_str = str(raw_doc or "").strip()
    if d_str:
        if d_str in doctor_map:
            return doctor_map[d_str]
        if d_str.upper() in doctor_map:
            return doctor_map[d_str.upper()]
        if d_str.isdigit() and str(int(d_str)) in doctor_map:
            return doctor_map[str(int(d_str))]
        if not d_str.isdigit():
            return d_str
    fb = str(fallback_name or "").strip()
    if fb:
        return fb
    return "GENERAL / UNASSIGNED"


def _format_payment_mode_company(pm_raw, pd_raw, company_raw="", is_insurance=False):
    pd = pd_raw
    if isinstance(pd, str):
        try:
            pd = json.loads(pd)
        except Exception:
            pd = {}
    if not isinstance(pd, dict):
        pd = {}

    pm = str(pd.get("method") or pm_raw or "Cash").strip()
    pm_upper = pm.upper()
    comp = str(company_raw or pd.get("company_name") or pd.get("insurance_company") or "").strip().upper()

    if is_insurance or comp or "INSURANCE" in pm_upper or "CREDIT" in pm_upper:
        if comp and comp not in ("GENERAL", "SELF", "CASH", "NONE", "NULL"):
            return f"INSURANCE - {comp}"
        if "INSURANCE" in pm_upper:
            return pm_upper
        if "CREDIT" in pm_upper and "CARD" not in pm_upper:
            return "CREDIT BILL"

    if any(k in pm_upper for k in ("CARD", "POS", "UPI", "GPAY", "PHONEPE", "PAYTM", "ONLINE", "BANK", "NEFT", "RTGS")):
        c_mach, c_type, _ = extract_card_metadata(pd, pm, 1.0)
        label = (c_type or c_mach or pm_upper).strip().upper()
        if "CARD" in label or "VISA" in label or "RUPAY" in label or "MASTER" in label:
            return f"CREDIT CARD - {label}" if not label.startswith("CREDIT CARD") else label
        return f"CREDIT CARD - {label}"

    return "CASH BILL"


def _calc_items_purchase_value(items_list, batch_cost_map, item_cost_map):
    if not isinstance(items_list, list):
        return 0.0
    total_pv = 0.0
    for it in items_list:
        if not isinstance(it, dict):
            continue
        iid = str(it.get("item_id") or "").strip()
        if not iid:
            continue
        qty = clean_num(it.get("qty") if it.get("qty") is not None else it.get("quantity"))
        if qty <= 0:
            continue
        batch = str(it.get("batch_number") or it.get("batch") or "").strip().upper()
        unit_cost = batch_cost_map.get((iid, batch)) or item_cost_map.get(iid) or 0.0
        total_pv += unit_cost * qty
    return round(total_pv, 2)


@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def doctor_revenue_report_api(request):
    """
    Doctor Revenue Report (Date Wise Bills Analysis Detailed).
    Groups all hospital bills (OP/IP Consultation, Investigations, Discharge, OP Pharmacy)
    by Doctor -> Bill Category, showing Bill Amount, Purchase Value, Net Total (Bill - Purchase),
    SH-Bill No, and Payment Mode & Company.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        from_str = data.get("from_date") or data.get("start_date")
        to_str = data.get("to_date") or data.get("end_date")
        outlet_code = str(data.get("outlet_code") or data.get("outlet") or "all").strip()
        doctor_filter = str(data.get("doctor_id") or data.get("doctor") or "all").strip()
        category_filter = str(data.get("category") or "all").strip()
        search_q = str(data.get("search") or "").strip().lower()
        is_refresh = str(data.get("refresh") or data.get("force_refresh") or "").lower() in ("true", "1")

        today_str = datetime.now().strftime("%Y-%m-%d")
        f_dt = parse_date(from_str or today_str)
        t_dt = parse_date(to_str or today_str, is_end=True)
        if not f_dt:
            f_dt = parse_date(today_str)
        if not t_dt:
            t_dt = parse_date(today_str, is_end=True)

        # Convert IST range to UTC for MongoDB datetime queries
        f_dt_utc = f_dt - timedelta(hours=5, minutes=30)
        t_dt_utc = t_dt - timedelta(hours=5, minutes=30)

        _, db, g_db = get_db()

        def _fetch_billtypes():
            by_no, by_id = {}, {}
            for b in db["hospital_billtype"].find({}, {"billTypeNo": 1, "bill_name": 1, "bill_type": 1, "billTypeName": 1}):
                name = str(b.get("bill_name") or b.get("billTypeName") or "").strip()
                if not name:
                    continue
                if b.get("billTypeNo"):
                    by_no[str(b["billTypeNo"]).strip()] = name
                if b.get("bill_type") is not None:
                    by_id[str(b["bill_type"]).strip()] = name
            return by_no, by_id

        def _fetch_billing():
            q = {"billed_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}, "is_active": {"$ne": False}}
            if outlet_code.lower() != "all":
                q["outlet_code"] = outlet_code
            return list(db["hospital_billing"].find(q, {
                "bill_number": 1, "bill_no": 1, "sh_bill_no": 1, "insurance_bill_number": 1,
                "billed_date": 1, "created_date": 1, "uhid": 1, "patient_name": 1, "patientname": 1,
                "bill_type": 1, "billTypeNo": 1, "doctor_id": 1, "total_fees": 1, "net_amount": 1,
                "consulting_fee": 1, "registration_fee": 1, "payment_method": 1, "payment_mode": 1,
                "payment_details": 1, "company_name": 1, "is_cancelled": 1, "outlet_code": 1
            }))

        def _fetch_invest():
            q = {
                "investBillDate": {"$gte": f_dt_utc, "$lte": t_dt_utc},
                "is_active": {"$ne": False},
                "paymentMethod": {"$regex": "^cash$", "$options": "i"},
                "paymentStatus": {"$regex": "^paid$", "$options": "i"},
            }
            if outlet_code.lower() != "all":
                q["outlet_code"] = outlet_code
            return list(db["hospital_investbilling"].find(q, {
                "investBillNo": 1, "bill_no": 1, "sh_bill_no": 1, "insurance_bill_number": 1,
                "investBillDate": 1, "created_date": 1, "uhid": 1, "ipNumber": 1,
                "patient_name": 1, "patientname": 1, "bill_type": 1, "billTypeNo": 1,
                "doctor": 1, "referredBy": 1, "finalPrice": 1, "total": 1,
                "paymentMethod": 1, "paymentStatus": 1, "payment_mode": 1, "payment_details": 1,
                "company_name": 1, "is_cancelled": 1, "item": 1, "outlet_code": 1
            }))

        def _fetch_discharge():
            q = {
                "bill_date": {"$gte": f_dt_utc, "$lte": t_dt_utc},
                "is_cancelled": {"$ne": True},
                "status": {"$nin": ["Estimate", "Cancelled"]},
            }
            if outlet_code.lower() != "all":
                q["outlet_code"] = outlet_code
            return list(db["hospital_dischargebilling"].find(q, {
                "bill_no": 1, "insurance_bill_number": 1, "sh_bill_no": 1,
                "bill_date": 1, "discharge_date": 1, "uhid": 1, "ipNumber": 1, "ip_number": 1,
                "patient_name": 1, "patientname": 1, "net_amount": 1, "total_amount": 1,
                "payment_method": 1, "payment_mode": 1, "payment_details": 1,
                "company_name": 1, "customer_type": 1, "is_insurance_bill": 1,
                "pharmacy_medicines": 1, "items": 1, "outlet_code": 1
            }))

        def _fetch_pharmacy():
            q = {
                "bill_date": {"$gte": f_dt_utc, "$lte": t_dt_utc},
                "billing_mode": "DIRECT",
                "is_deleted": {"$ne": True},
                "billing_status": {"$nin": ["Cancelled", "Estimate", "deleted"]},
            }
            if outlet_code.lower() != "all":
                q["outlet_code"] = outlet_code
            return list(db["hospital_pharmacybilling"].find(q, {
                "bill_no": 1, "sh_bill_no": 1, "bill_date": 1, "uhid": 1,
                "patientname": 1, "patient_name": 1, "doctor_id": 1,
                "net_amount": 1, "total_amount": 1, "payment_mode": 1,
                "payment_details": 1, "customer_type": 1, "company_name": 1,
                "is_insurance": 1, "medicine_particulars": 1, "items": 1,
                "bill_type": 1, "outlet_code": 1
            }))

        with ThreadPoolExecutor(max_workers=6) as executor:
            f_bt = executor.submit(_fetch_billtypes)
            f_b = executor.submit(_fetch_billing)
            f_i = executor.submit(_fetch_invest)
            f_d = executor.submit(_fetch_discharge)
            f_p = executor.submit(_fetch_pharmacy)
            f_grn = executor.submit(_get_grn_cost_maps, db, is_refresh)
            f_doc = executor.submit(_get_doctor_map, g_db, is_refresh)

            billtype_no_map, billtype_id_map = f_bt.result()
            billing_docs = f_b.result()
            invest_docs = f_i.result()
            discharge_docs = f_d.result()
            pharm_docs = f_p.result()
            batch_cost_map, item_cost_map = f_grn.result()
            doctor_map = f_doc.result()

        # Resolve admissions for discharge bills (doctor & company) and patients for names/company
        ip_numbers = list({
            str(d.get("ipNumber") or d.get("ip_number") or "").strip()
            for d in discharge_docs if (d.get("ipNumber") or d.get("ip_number"))
        })
        all_uhids = list({
            str(doc.get("uhid") or "").strip()
            for col_docs in (billing_docs, invest_docs, discharge_docs, pharm_docs)
            for doc in col_docs if doc.get("uhid")
        })

        adm_map = {}
        if ip_numbers:
            for adm in db["hospital_admission"].find(
                {"ipNumber": {"$in": ip_numbers}},
                {"ipNumber": 1, "consultingDoctor": 1, "admittingDoctor": 1, "insurance_company": 1, "company_name": 1, "patient_name": 1, "patientname": 1}
            ):
                ip_k = str(adm.get("ipNumber") or "").strip()
                if ip_k:
                    adm_map[ip_k] = adm

        patient_map = {}
        if all_uhids:
            for pat in db["hospital_patient"].find(
                {"uhid": {"$in": all_uhids}},
                {"uhid": 1, "firstName": 1, "lastName": 1, "patient_name": 1, "patientname": 1, "company_name": 1, "insurance_company": 1}
            ):
                u_k = str(pat.get("uhid") or "").strip()
                if u_k:
                    patient_map[u_k] = pat

        def _resolve_patient(uhid_val, fallback_name=""):
            u_k = str(uhid_val or "").strip()
            pat = patient_map.get(u_k)
            if pat:
                nm = str(
                    pat.get("patient_name")
                    or pat.get("patientname")
                    or f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip()
                    or ""
                ).strip()
                if nm:
                    return nm, str(pat.get("company_name") or pat.get("insurance_company") or "").strip()
            return str(fallback_name or "GENERAL PATIENT").strip(), ""

        raw_rows = []

        # 1. hospital_billing (Consultations / Registration)
        for b in billing_docs:
            if b.get("is_cancelled"):
                continue
            b_no = str(b.get("bill_number") or b.get("bill_no") or "").strip()
            if not b_no:
                continue
            amt = clean_num(b.get("total_fees") or b.get("net_amount") or (clean_num(b.get("consulting_fee")) + clean_num(b.get("registration_fee"))))
            if amt <= 0:
                continue
            bt_id = str(b.get("bill_type") or "").strip()
            bt_no = str(b.get("billTypeNo") or "").strip()
            cat_name = billtype_no_map.get(bt_no) or billtype_id_map.get(bt_id) or "CONSULTATION / BILLING"
            uhid = str(b.get("uhid") or "").strip()
            pat_name, pat_comp = _resolve_patient(uhid, b.get("patient_name") or b.get("patientname"))
            doc_id = str(b.get("doctor_id") or "").strip()
            doc_name = _resolve_doc_name(doc_id, doctor_map)
            dt_ist = to_ist(b.get("billed_date") or b.get("created_date"))
            pm_comp = _format_payment_mode_company(
                b.get("payment_method") or b.get("payment_mode"),
                b.get("payment_details"),
                b.get("company_name") or pat_comp,
                is_insurance=bool(b.get("insurance_bill_number"))
            )
            raw_rows.append({
                "doctor_id": doc_id or "UNASSIGNED",
                "doctor_name": doc_name,
                "category": cat_name.upper(),
                "bill_date": dt_ist.strftime("%d/%m/%Y") if isinstance(dt_ist, datetime) else "",
                "_sort_dt": dt_ist.strftime("%Y-%m-%d %H:%M:%S") if isinstance(dt_ist, datetime) else "",
                "bill_number": b_no,
                "sh_bill_no": str(b.get("sh_bill_no") or b.get("insurance_bill_number") or "").strip(),
                "op_number": uhid,
                "patient_name": pat_name.upper(),
                "bill_amount": round(amt, 2),
                "purchase_value": 0.0,
                "total": round(amt, 2),
                "payment_mode_company": pm_comp,
            })

        # 2. hospital_investbilling (CT, MRI, Lab, ECG, PET_CT, etc.)
        for inv in invest_docs:
            if inv.get("is_cancelled"):
                continue
            b_no = str(inv.get("investBillNo") or inv.get("bill_no") or "").strip()
            if not b_no:
                continue
            amt = clean_num(inv.get("finalPrice") or inv.get("total"))
            bt_no = str(inv.get("billTypeNo") or "").strip()
            bt_id = str(inv.get("bill_type") or "").strip()
            cat_name = billtype_no_map.get(bt_no) or billtype_id_map.get(bt_id)
            if not cat_name and isinstance(inv.get("item"), list) and inv["item"]:
                first_bt = str(inv["item"][0].get("billTypeNo") or "").strip() if isinstance(inv["item"][0], dict) else ""
                cat_name = billtype_no_map.get(first_bt)
            cat_name = cat_name or "INVESTIGATION (SH)"
            if "(SH)" not in cat_name.upper() and "PET" not in cat_name.upper():
                cat_name = f"{cat_name} (SH)"

            uhid = str(inv.get("uhid") or "").strip()
            pat_name, pat_comp = _resolve_patient(uhid, inv.get("patient_name") or inv.get("patientname"))
            doc_id = str(inv.get("doctor") or inv.get("referredBy") or "").strip()
            doc_name = _resolve_doc_name(doc_id, doctor_map)
            dt_ist = to_ist(inv.get("investBillDate") or inv.get("created_date"))
            pm_comp = _format_payment_mode_company(
                inv.get("paymentMethod") or inv.get("payment_mode"),
                inv.get("payment_details"),
                inv.get("company_name") or pat_comp,
                is_insurance=bool(inv.get("insurance_bill_number"))
            )
            raw_rows.append({
                "doctor_id": doc_id or "UNASSIGNED",
                "doctor_name": doc_name,
                "category": cat_name.upper(),
                "bill_date": dt_ist.strftime("%d/%m/%Y") if isinstance(dt_ist, datetime) else "",
                "_sort_dt": dt_ist.strftime("%Y-%m-%d %H:%M:%S") if isinstance(dt_ist, datetime) else "",
                "bill_number": b_no,
                "sh_bill_no": str(inv.get("sh_bill_no") or inv.get("insurance_bill_number") or "").strip(),
                "op_number": uhid,
                "patient_name": pat_name.upper(),
                "bill_amount": round(amt, 2),
                "purchase_value": 0.0,
                "total": round(amt, 2),
                "payment_mode_company": pm_comp,
            })

        # 3. hospital_dischargebilling (DISCHARGE)
        for dis in discharge_docs:
            b_no = str(dis.get("bill_no") or "").strip()
            if not b_no:
                continue
            tot_amt = clean_num(dis.get("total_amount"))
            amt = tot_amt if tot_amt > 0 else clean_num(dis.get("net_amount"))
            pv = _calc_items_purchase_value(dis.get("pharmacy_medicines") or [], batch_cost_map, item_cost_map)
            ip_no = str(dis.get("ipNumber") or dis.get("ip_number") or "").strip()
            adm = adm_map.get(ip_no, {})
            uhid = str(dis.get("uhid") or "").strip()
            pat_name, pat_comp = _resolve_patient(
                uhid,
                dis.get("patient_name") or dis.get("patientname") or adm.get("patient_name") or adm.get("patientname")
            )
            doc_id = str(adm.get("consultingDoctor") or adm.get("admittingDoctor") or "").strip()
            doc_name = _resolve_doc_name(doc_id, doctor_map)
            dt_ist = to_ist(dis.get("bill_date") or dis.get("discharge_date"))
            comp = str(dis.get("company_name") or adm.get("insurance_company") or adm.get("company_name") or pat_comp or "").strip()
            pm_comp = _format_payment_mode_company(
                dis.get("payment_method") or dis.get("payment_mode"),
                dis.get("payment_details"),
                comp,
                is_insurance=bool(dis.get("is_insurance_bill") or str(dis.get("customer_type") or "").upper() == "INSURANCE")
            )
            raw_rows.append({
                "doctor_id": doc_id or "UNASSIGNED",
                "doctor_name": doc_name,
                "category": "DISCHARGE",
                "bill_date": dt_ist.strftime("%d/%m/%Y") if isinstance(dt_ist, datetime) else "",
                "_sort_dt": dt_ist.strftime("%Y-%m-%d %H:%M:%S") if isinstance(dt_ist, datetime) else "",
                "bill_number": b_no,
                "sh_bill_no": str(dis.get("sh_bill_no") or dis.get("insurance_bill_number") or "").strip(),
                "op_number": uhid,
                "patient_name": pat_name.upper(),
                "bill_amount": round(amt, 2),
                "purchase_value": round(pv, 2),
                "total": round(amt - pv, 2),
                "payment_mode_company": pm_comp,
            })

        # 4. hospital_pharmacybilling (PHARMACY OP BILL (SH))
        for pb in pharm_docs:
            b_no = str(pb.get("bill_no") or "").strip()
            if not b_no:
                continue
            amt = clean_num(pb.get("net_amount") or pb.get("total_amount"))
            meds = pb.get("medicine_particulars") or pb.get("items") or []
            pv = _calc_items_purchase_value(meds, batch_cost_map, item_cost_map)
            uhid = str(pb.get("uhid") or "").strip()
            pat_name, pat_comp = _resolve_patient(uhid, pb.get("patientname") or pb.get("patient_name"))
            doc_id = str(pb.get("doctor_id") or "").strip()
            doc_name = _resolve_doc_name(doc_id, doctor_map)
            dt_ist = to_ist(pb.get("bill_date"))
            pm_comp = _format_payment_mode_company(
                pb.get("payment_mode"),
                pb.get("payment_details"),
                pb.get("company_name") or pat_comp,
                is_insurance=bool(pb.get("is_insurance"))
            )
            raw_rows.append({
                "doctor_id": doc_id or "UNASSIGNED",
                "doctor_name": doc_name,
                "category": "PHARMACY OP BILL (SH)",
                "bill_date": dt_ist.strftime("%d/%m/%Y") if isinstance(dt_ist, datetime) else "",
                "_sort_dt": dt_ist.strftime("%Y-%m-%d %H:%M:%S") if isinstance(dt_ist, datetime) else "",
                "bill_number": b_no,
                "sh_bill_no": str(pb.get("sh_bill_no") or "").strip(),
                "op_number": uhid,
                "patient_name": pat_name.upper(),
                "bill_amount": round(amt, 2),
                "purchase_value": round(pv, 2),
                "total": round(amt - pv, 2),
                "payment_mode_company": pm_comp,
            })

        # Collect distinct filter options before applying user filters
        doctors_opt_map = {}
        categories_set = set()
        for r in raw_rows:
            doctors_opt_map[r["doctor_id"]] = r["doctor_name"]
            categories_set.add(r["category"])

        doctors_options = sorted(
            [{"doctor_id": k, "doctor_name": v} for k, v in doctors_opt_map.items()],
            key=lambda x: x["doctor_name"]
        )
        categories_options = sorted(list(categories_set))

        # Apply filters
        filtered_rows = []
        for r in raw_rows:
            if doctor_filter.lower() != "all":
                if r["doctor_id"].lower() != doctor_filter.lower() and r["doctor_name"].lower() != doctor_filter.lower():
                    continue
            if category_filter.lower() != "all":
                if r["category"].lower() != category_filter.lower():
                    continue
            if search_q:
                haystack = f"{r['doctor_name']} {r['patient_name']} {r['op_number']} {r['bill_number']} {r['sh_bill_no']} {r['payment_mode_company']} {r['category']}".lower()
                if search_q not in haystack:
                    continue
            filtered_rows.append(r)

        # Group by Doctor -> Category
        doc_groups = {}
        for r in filtered_rows:
            d_key = (r["doctor_id"], r["doctor_name"])
            if d_key not in doc_groups:
                doc_groups[d_key] = {}
            c_key = r["category"]
            if c_key not in doc_groups[d_key]:
                doc_groups[d_key][c_key] = []
            doc_groups[d_key][c_key].append(r)

        doctors_list = []
        grand_bill_amt = 0.0
        grand_purch_val = 0.0
        grand_total = 0.0
        grand_count = 0

        for doc_idx, ((d_id, d_name), cats_dict) in enumerate(
            sorted(doc_groups.items(), key=lambda kv: kv[0][1]), start=1
        ):
            categories_list = []
            doc_bill_amt = 0.0
            doc_purch_val = 0.0
            doc_total = 0.0
            doc_count = 0

            for cat_idx, (cat_name, rows_in_cat) in enumerate(
                sorted(cats_dict.items(), key=lambda kv: kv[0]), start=1
            ):
                rows_in_cat.sort(key=lambda x: (x["_sort_dt"], x["bill_number"]))
                formatted_rows = []
                cat_bill_amt = 0.0
                cat_purch_val = 0.0
                cat_total = 0.0

                for r_idx, row in enumerate(rows_in_cat, start=1):
                    cat_bill_amt += row["bill_amount"]
                    cat_purch_val += row["purchase_value"]
                    cat_total += row["total"]
                    formatted_rows.append({
                        "sl_no": r_idx,
                        "bill_date": row["bill_date"],
                        "bill_number": row["bill_number"],
                        "sh_bill_no": row["sh_bill_no"],
                        "op_number": row["op_number"],
                        "patient_name": row["patient_name"],
                        "bill_amount": round(row["bill_amount"], 2),
                        "purchase_value": round(row["purchase_value"], 2),
                        "total": round(row["total"], 2),
                        "payment_mode_company": row["payment_mode_company"],
                    })

                doc_bill_amt += cat_bill_amt
                doc_purch_val += cat_purch_val
                doc_total += cat_total
                doc_count += len(formatted_rows)

                categories_list.append({
                    "cat_sl_no": cat_idx,
                    "category_name": cat_name,
                    "bill_count": len(formatted_rows),
                    "bill_amount": round(cat_bill_amt, 2),
                    "purchase_value": round(cat_purch_val, 2),
                    "total": round(cat_total, 2),
                    "rows": formatted_rows,
                })

            grand_bill_amt += doc_bill_amt
            grand_purch_val += doc_purch_val
            grand_total += doc_total
            grand_count += doc_count

            doctors_list.append({
                "doctor_sl_no": doc_idx,
                "doctor_id": d_id,
                "doctor_name": d_name,
                "bill_count": doc_count,
                "bill_amount": round(doc_bill_amt, 2),
                "purchase_value": round(doc_purch_val, 2),
                "total": round(doc_total, 2),
                "categories": categories_list,
            })

        return Response({
            "success": True,
            "report_title": "DATE WISE BILLS ANALYSIS DETAILED",
            "date_range": {
                "from_date": f_dt.strftime("%Y-%m-%d"),
                "to_date": t_dt.strftime("%Y-%m-%d"),
                "from_display": f_dt.strftime("%d/%m/%Y"),
                "to_display": t_dt.strftime("%d/%m/%Y"),
            },
            "printed_at": datetime.now().strftime("%d/%m/%Y at %H:%M:%S"),
            "doctors": doctors_list,
            "doctors_options": doctors_options,
            "categories_options": categories_options,
            "summary": {
                "total_doctors": len(doctors_list),
                "total_bills": grand_count,
                "total_bill_amount": round(grand_bill_amt, 2),
                "total_purchase_value": round(grand_purch_val, 2),
                "grand_total": round(grand_total, 2),
            },
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
