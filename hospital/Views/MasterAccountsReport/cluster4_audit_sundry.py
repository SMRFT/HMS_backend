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
from hospital.Views.dbcollection import resolve_created_by_name

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def accounts_audit_report_api(request):
    """
    Dedicated Accounts Audit Report API.
    Transactional audit trail across Registration, Pharmacy, Investigation, and Sales Returns / Refunds.
    Checks bill types properly, fetches approved investigation refunds from hospital_investrefund
    (linked to hospital_investbilling with is_approved: True), and displays requested_by, approved_by,
    and itemized billing details.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        from_f = data.get("from_date") or data.get("start_date")
        to_f = data.get("to_date") or data.get("end_date")
        outlet_code = data.get("outlet_code") or data.get("outlet")
        source_param = str(data.get("source") or "all").strip().lower()

        is_refresh = str(data.get("refresh") or data.get("force_refresh") or "").lower() in ["true", "1"]
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=from_f,
            to_str=to_f,
            outlet_code=outlet_code,
            force_refresh=is_refresh
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

        # Pre-cache employee profiles in bulk for instant O(1) in-memory lookups (100x speedup)
        emp_cache = {}
        try:
            if g_db is not None:
                prof_docs = list(g_db["backend_diagnostics_profile"].find(
                    {}, 
                    {"employeeId": 1, "employeeName": 1, "name": 1, "firstName": 1, "lastName": 1, "_id": 0}
                ))
                for p in prof_docs:
                    eid = str(p.get("employeeId") or "").strip()
                    ename = p.get("employeeName") or p.get("name") or f"{p.get('firstName') or ''} {p.get('lastName') or ''}".strip()
                    if eid and ename:
                        emp_cache[eid] = ename
                        if eid.isdigit():
                            emp_cache[str(int(eid))] = ename
                            emp_cache[f"{int(eid):04d}"] = ename
                            emp_cache[f"{int(eid):05d}"] = ename
        except Exception:
            pass

        def resolve_emp_fast(emp_id, default="Staff"):
            if not emp_id:
                return default
            val = str(emp_id).strip()
            if not val:
                return default
            return emp_cache.get(val) or emp_cache.get(val.lstrip("0")) or (val if not any(c.isdigit() for c in val) else default)

        # Build Bill Type Master Map
        billtype_map = {}
        try:
            for bt in db["hospital_billtype"].find({"is_active": {"$ne": False}}, {"billTypeNo": 1, "billTypeName": 1, "department": 1, "_id": 0}):
                code = str(bt.get("billTypeNo") or "").strip()
                name = bt.get("billTypeName") or bt.get("department") or code
                if code:
                    billtype_map[code] = name
                    billtype_map[code.upper()] = name
        except Exception:
            pass
        
        try:
            f_d = parse_date(from_f)
            t_d = parse_date(to_f, is_end=True)
            f_utc = (f_d - timedelta(hours=5, minutes=30)) if f_d else None
            t_utc = (t_d - timedelta(hours=5, minutes=30)) if t_d else None
            f_str = f_d.strftime("%Y-%m-%d") if f_d else None
            t_str = t_d.strftime("%Y-%m-%d") if t_d else None
            
            # 1. Edit History from Registration (filtered by date & outlet to prevent full table scan)
            b_edit_query = {"edit_history": {"$exists": True, "$ne": []}}
            if outlet_code and str(outlet_code).lower() != "all":
                b_edit_query["outlet_code"] = outlet_code
            if f_utc and t_utc:
                b_edit_query["created_date"] = {"$gte": f_utc - timedelta(days=7), "$lte": t_utc + timedelta(days=1)}

            b_edits = list(db["hospital_billing"].find(
                b_edit_query,
                {"edit_history": 1, "bill_number": 1, "bill_no": 1, "billed_date": 1, "created_date": 1,
                 "created_by": 1, "lastmodified_by": 1, "uhid": 1, "patient_name": 1, "total_fees": 1, "items": 1}
            ))

            for b in b_edits:
                for eh in (b.get("edit_history") or []):
                    if not isinstance(eh, dict): continue
                    dt_s = format_ist_date(eh.get("edited_date") or b.get("billed_date"))
                    if f_d and dt_s < str(f_d)[:10]: continue
                    if t_d and dt_s > str(t_d)[:10]: continue

                    req_id = eh.get("requested_by") or b.get("created_by") or ""
                    appr_id = eh.get("edited_by_name") or eh.get("edited_by") or b.get("lastmodified_by") or "STAFF"
                    req_name = resolve_emp_fast(req_id, "Registration Staff")
                    appr_name = resolve_emp_fast(appr_id, "Admin")

                    audit_rows.append({
                        "source": "Registration Billing",
                        "bill_type": "Registration",
                        "record_no": b.get("bill_number") or b.get("bill_no"),
                        "original_bill_no": b.get("bill_number") or b.get("bill_no"),
                        "uhid": b.get("uhid") or "",
                        "patient_name": b.get("patient_name") or "Patient",
                        "description": eh.get("description") or eh.get("reason") or "Billing Rate / Fee Modification",
                        "old_value": str(eh.get("old_value") if eh.get("old_value") is not None else "-"),
                        "new_value": str(eh.get("new_value") if eh.get("new_value") is not None else clean_num(b.get("total_fees"))),
                        "requested_by": req_name,
                        "requested_by_id": str(req_id),
                        "approved_by": appr_name,
                        "approved_by_id": str(appr_id),
                        "edited_by_name": appr_name,
                        "edited_date": dt_s,
                        "is_approved": True,
                        "billing_details": [{"name": "Registration Fee Modification", "quantity": 1, "amount": clean_num(b.get("total_fees"))}]
                    })
                    by_source["Registration Billing"] += 1

            # 2. Approved Investigation Refunds from hospital_investrefund (linked to hospital_investbilling)
            ir_base = [
                {"is_active": {"$ne": False}},
                {"is_approved": {"$ne": False}},
                {"$or": [
                    {"is_approved": True},
                    {"status": {"$in": ["Paid", "Completed", "Approved"]}},
                    {"paymentStatus": {"$in": ["Paid", "Completed", "Approved"]}},
                    {"payment_status": "Refund"}
                ]}
            ]
            if f_utc and t_utc and f_str and t_str:
                ir_base.append({"$or": [
                    {"refundBillDate": {"$gte": f_utc, "$lte": t_utc}},
                    {"paid_date": {"$gte": f_utc, "$lte": t_utc}},
                    {"created_date": {"$gte": f_utc, "$lte": t_utc}},
                    {"investBillDate": {"$gte": f_utc, "$lte": t_utc}},
                    {"refund_datetime": {"$gte": f_str, "$lte": t_str + " 23:59:59"}},
                    {"paid_at": {"$gte": f_str, "$lte": t_str + " 23:59:59"}}
                ]})
            if outlet_code and str(outlet_code).lower() != "all":
                ir_base.append({"outlet_code": outlet_code})

            inv_refund_docs = list(db["hospital_investrefund"].find(
                {"$and": ir_base},
                {"investBillNo": 1, "billTypeNo": 1, "requested_by": 1, "created_by": 1, "approved_by": 1,
                 "lastmodified_by": 1, "CashierID": 1, "refund_finalPrice": 1, "refund_amount": 1,
                 "refundBillDate": 1, "paid_date": 1, "created_date": 1, "investBillDate": 1,
                 "refundBillNo": 1, "uhid": 1, "patientName": 1, "refundRemarks": 1, "item": 1, "items": 1}
            ))
            
            # Pre-fetch original hospital_investbilling for these refunds
            inv_orig_nos = [str(r.get("investBillNo") or "").strip() for r in inv_refund_docs if r.get("investBillNo")]
            inv_orig_map = {}
            if inv_orig_nos:
                for ib in db["hospital_investbilling"].find({"investBillNo": {"$in": inv_orig_nos}}, {"investBillNo": 1, "billTypeNo": 1, "finalPrice": 1, "total": 1}):
                    inv_orig_map[str(ib.get("investBillNo")).strip()] = ib

            for ir in inv_refund_docs:
                orig_bno = str(ir.get("investBillNo") or "").strip()
                inv_b = inv_orig_map.get(orig_bno, {})

                bt_no = ir.get("billTypeNo") or inv_b.get("billTypeNo") or "INVEST"
                bt_name = billtype_map.get(str(bt_no).strip()) or bt_no

                req_id = ir.get("requested_by") or ir.get("created_by") or ""
                appr_id = ir.get("approved_by") or ir.get("lastmodified_by") or ir.get("CashierID") or ""
                req_name = resolve_emp_fast(req_id, "Lab / Staff")
                appr_name = resolve_emp_fast(appr_id, "Cashier")

                ret_amt = clean_num(ir.get("refund_finalPrice") or ir.get("refund_amount") or 0.0)
                orig_amt = clean_num(inv_b.get("finalPrice") or inv_b.get("total") or ret_amt)

                dt_val = ir.get("refundBillDate") or ir.get("paid_date") or ir.get("created_date") or ir.get("investBillDate")
                dt_str = format_ist_date(dt_val)

                raw_items = ir.get("item") or ir.get("items") or []
                item_details = []
                for it in (raw_items if isinstance(raw_items, list) else []):
                    if isinstance(it, dict):
                        item_details.append({
                            "name": str(it.get("itemName") or it.get("test_name") or "Investigation Test"),
                            "quantity": clean_num(it.get("quantity") or 1),
                            "amount": clean_num(it.get("price") or it.get("rate") or 0.0)
                        })

                # Classify under Investigation Billing (Refund) and Sales Return
                audit_rows.append({
                    "source": "Investigation Billing",
                    "bill_type": f"{bt_name} Refund",
                    "record_no": ir.get("refundBillNo") or str(ir.get("_id")),
                    "original_bill_no": orig_bno or "-",
                    "uhid": ir.get("uhid") or "",
                    "patient_name": ir.get("patientName") or "Patient",
                    "description": f"Approved Investigation Refund ({bt_name}): {ir.get('refundRemarks') or 'Test Refunded'}",
                    "old_value": str(round(orig_amt, 2)),
                    "new_value": str(round(ret_amt, 2)),
                    "requested_by": req_name,
                    "requested_by_id": str(req_id),
                    "approved_by": appr_name,
                    "approved_by_id": str(appr_id),
                    "edited_by_name": appr_name,
                    "edited_date": dt_str,
                    "is_approved": True,
                    "is_refund": True,
                    "billing_details": item_details
                })
                by_source["Investigation Billing"] += 1
                by_source["Sales Return"] = by_source.get("Sales Return", 0) + 1
                    
            # 3. True Edit History from Admissions (Doctor changes, Insurance changes, Room changes)
            adm_docs = list(db["hospital_admission"].find(
                {"edit_history.0": {"$exists": True}},
                {"ip_number": 1, "inpatient_number": 1, "uhid": 1, "patient_name": 1, "edit_history": 1, "admission_date": 1, "created_date": 1}
            ))
            for a in adm_docs:
                uhid_val = a.get("uhid") or ""
                p_name = a.get("patient_name") or "Patient"
                ip_no = a.get("ip_number") or a.get("inpatient_number") or ""
                for eh in (a.get("edit_history") or []):
                    if not isinstance(eh, dict):
                        continue
                    dt_s = format_ist_date(eh.get("edited_date") or eh.get("date") or a.get("created_date"))
                    if f_d and dt_s < str(f_d)[:10]:
                        continue
                    if t_d and dt_s > str(t_d)[:10]:
                        continue

                    editor_id = eh.get("edited_by") or eh.get("created_by") or ""
                    editor_name = resolve_emp_fast(editor_id, "Admin Staff")
                    reason = eh.get("edited_reason") or eh.get("reason") or "Admission Details Modified"

                    audit_rows.append({
                        "source": "Registration Billing",
                        "bill_type": "IP Admission Modification",
                        "record_no": ip_no or uhid_val,
                        "original_bill_no": ip_no or uhid_val,
                        "uhid": uhid_val,
                        "patient_name": p_name,
                        "description": f"Admission Edit: {reason}",
                        "old_value": str(eh.get("old_value") if eh.get("old_value") is not None else "-"),
                        "new_value": str(eh.get("new_value") if eh.get("new_value") is not None else "-"),
                        "requested_by": editor_name,
                        "requested_by_id": str(editor_id),
                        "approved_by": editor_name,
                        "approved_by_id": str(editor_id),
                        "edited_by_name": editor_name,
                        "edited_date": dt_s,
                        "is_approved": True,
                        "billing_details": [{"name": reason, "quantity": 1, "amount": 0.0}]
                    })
                    by_source["Registration Billing"] += 1

            # 4. True Edit History from Pharmacy Billing (Sales Returns, Quantity/Item Modifications)
            pharm_docs = list(db["hospital_pharmacybilling"].find(
                {"medicine_particulars.edit_history.0": {"$exists": True}},
                {"bill_no": 1, "Bill_id": 1, "uhid": 1, "patient_name": 1, "medicine_particulars": 1, "created_date": 1, "date": 1}
            ))
            for pb in pharm_docs:
                b_no = pb.get("bill_no") or pb.get("Bill_id")
                uhid_val = pb.get("uhid") or ""
                p_name = pb.get("patient_name") or "Patient"
                for mp in (pb.get("medicine_particulars") or []):
                    if not isinstance(mp, dict) or not mp.get("edit_history"):
                        continue
                    item_name = mp.get("item_name") or mp.get("name") or "Medicine Item"
                    for eh in (mp.get("edit_history") or []):
                        if not isinstance(eh, dict):
                            continue
                        dt_s = format_ist_date(eh.get("return_date") or eh.get("changed_at") or eh.get("edited_date") or pb.get("created_date"))
                        if f_d and dt_s < str(f_d)[:10]:
                            continue
                        if t_d and dt_s > str(t_d)[:10]:
                            continue

                        editor_id = eh.get("edited_by") or eh.get("changed_by") or ""
                        editor_name = resolve_emp_fast(editor_id, "Pharmacy Staff")
                        action = eh.get("action") or "Item Edited"
                        old_q = eh.get("old_qty")
                        new_q = eh.get("new_qty") or eh.get("return_qty")
                        ret_bill = eh.get("return_bill_no") or b_no

                        src = "Sales Return" if "return" in str(action).lower() else "Pharmacy Billing"
                        by_source[src] = by_source.get(src, 0) + 1

                        audit_rows.append({
                            "source": src,
                            "bill_type": "Pharmacy Modification",
                            "record_no": ret_bill or b_no,
                            "original_bill_no": b_no,
                            "uhid": uhid_val,
                            "patient_name": p_name,
                            "description": f"{action.replace('_', ' ').title()}: {item_name} (Qty: {old_q} -> {new_q})",
                            "old_value": str(old_q if old_q is not None else "-"),
                            "new_value": str(new_q if new_q is not None else "-"),
                            "requested_by": editor_name,
                            "requested_by_id": str(editor_id),
                            "approved_by": editor_name,
                            "approved_by_id": str(editor_id),
                            "edited_by_name": editor_name,
                            "edited_date": dt_s,
                            "is_approved": True,
                            "billing_details": [{"name": item_name, "quantity": clean_num(new_q or 1), "amount": clean_num(mp.get("total") or 0.0)}]
                        })

            # 5. Sales Returns from hospital_salesreturn (Direct Pharmacy & Other Sales Returns)
            sr_q = {}
            if outlet_code and str(outlet_code).lower() != "all":
                sr_q["outlet_code"] = outlet_code
            if f_utc and t_utc:
                sr_q["$or"] = [
                    {"created_date": {"$gte": f_utc, "$lte": t_utc}},
                    {"return_date": {"$gte": f_str, "$lte": t_str + " 23:59:59"}}
                ]

            sr_docs = list(db["hospital_salesreturn"].find(
                sr_q,
                {"sales_return_number": 1, "return_no": 1, "return_date": 1, "created_date": 1,
                 "uhid": 1, "patient_name": 1, "inpatient_number": 1, "return_amount": 1,
                 "total_amount": 1, "created_by": 1, "returned_items": 1}
            ))
            for sr in sr_docs:
                sr_no = sr.get("sales_return_number") or sr.get("return_no") or str(sr.get("_id"))
                dt_val = sr.get("return_date") or sr.get("created_date")
                dt_s = format_ist_date(dt_val)
                if f_d and dt_s < str(f_d)[:10]:
                    continue
                if t_d and dt_s > str(t_d)[:10]:
                    continue

                c_by = sr.get("created_by") or ""
                staff_name = resolve_emp_fast(c_by, "Pharmacy Cashier")
                amt = clean_num(sr.get("return_amount") or sr.get("total_amount") or 0.0)

                items = sr.get("returned_items") or []
                det = []
                if isinstance(items, list):
                    for it in items[:10]:
                        if isinstance(it, dict):
                            det.append({
                                "name": it.get("item_name") or it.get("name") or "Returned Medicine",
                                "quantity": clean_num(it.get("quantity") or it.get("return_quantity") or 1),
                                "amount": clean_num(it.get("amount") or it.get("price") or 0.0)
                            })

                audit_rows.append({
                    "source": "Sales Return",
                    "bill_type": "Pharmacy Sales Return",
                    "record_no": sr_no,
                    "original_bill_no": sr.get("original_bill_no") or "-",
                    "uhid": sr.get("uhid") or "",
                    "patient_name": sr.get("patient_name") or "Patient",
                    "description": f"Approved Pharmacy Sales Return: ₹{amt:.2f}",
                    "old_value": str(round(amt, 2)),
                    "new_value": "0.00",
                    "requested_by": staff_name,
                    "requested_by_id": str(c_by),
                    "approved_by": staff_name,
                    "approved_by_id": str(c_by),
                    "edited_by_name": staff_name,
                    "edited_date": dt_s,
                    "is_approved": True,
                    "is_refund": True,
                    "billing_details": det
                })
                by_source["Sales Return"] = by_source.get("Sales Return", 0) + 1
        except Exception as e:
            raise e
            
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
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
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
        is_refresh = str(data.get("refresh") or data.get("force_refresh") or "").lower() in ["true", "1"]
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet"),
            shift_no=data.get("shiftno") or data.get("shift_no"),
            force_refresh=is_refresh
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

        # Sort by bill number order wise (natural numeric comparison)
        def get_bill_sort_key(b):
            bno = str(b.get("bill_no") or "").strip()
            digits = "".join(c for c in bno if c.isdigit())
            num_val = int(digits) if digits else 0
            return (num_val, bno)

        sorted_bills = sorted(all_items, key=get_bill_sort_key)
        
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
                desc_raw = d.get("description") or ""
                pt_n = ""
                rm_n = ""
                ds_t = ""
                if isinstance(desc_raw, str) and desc_raw.strip().startswith("{") and desc_raw.strip().endswith("}"):
                    try:
                        p_data = json.loads(desc_raw)
                        pt_n = str(p_data.get("patient_name") or p_data.get("name") or "").strip()
                        rm_n = str(p_data.get("room_no") or "").strip()
                        ds_t = str(p_data.get("description") or p_data.get("narration") or p_data.get("reason") or "").strip()
                    except Exception:
                        ds_t = desc_raw
                elif isinstance(desc_raw, dict):
                    pt_n = str(desc_raw.get("patient_name") or desc_raw.get("name") or "").strip()
                    rm_n = str(desc_raw.get("room_no") or "").strip()
                    ds_t = str(desc_raw.get("description") or desc_raw.get("narration") or desc_raw.get("reason") or "").strip()
                else:
                    ds_t = str(desc_raw or "").strip()

                party_name = pt_n or d.get("paid_to_or_received_from") or "-"
                if party_name == "-" and ds_t.upper().startswith("PAID TO "):
                    party_name = ds_t.split("(", 1)[0].replace("PAID TO ", "").replace("Paid to ", "").replace("paid to ", "").strip()

                if ds_t and rm_n:
                    narration = f"{ds_t} (Room {rm_n})"
                elif ds_t:
                    narration = ds_t
                elif rm_n:
                    narration = rm_n if rm_n.lower().startswith("room") else f"Room {rm_n}"
                else:
                    narration = d.get("narration") or ("Counter Expense" if v_type == "Payment" else "Sundry Receipt")

                c_id = str(d.get("CashierID") or d.get("created_by") or "")
                c_name = cashier_map.get(c_id, c_id)
                v_date = d.get("voucher_date") or d.get("created_date")
                dt_str = format_ist_datetime(v_date) if v_date else ""
                d_only = format_ist_date(v_date) if v_date else ""
                t_only = format_ist_time(v_date) if v_date else ""
                
                vouchers.append({
                    "voucher_no": d.get("voucher_no") or str(d.get("_id"))[-8:],
                    "date": dt_str,
                    "voucher_date": d_only or (dt_str.split(" ")[0] if " " in dt_str else dt_str),
                    "voucher_time": t_only or (dt_str.split(" ", 1)[1] if " " in dt_str else ""),
                    "voucher_type": v_type,
                    "account_head": str(d.get("account_head") or "Sundry"),
                    "paid_to_or_received_from": party_name,
                    "amount": amt,
                    "cashier_id": c_id,
                    "cashier_name": c_name,
                    "narration": narration
                })

            # Ingest Sales Returns as Payments (counter cash refund)
            sr_q = {"$or": [
                {"created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
                {"return_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
                {"return_bill_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
                {"paid_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
                {"refund_datetime": {"$gte": f_dt_utc, "$lte": t_dt_utc}}
            ]}
            if outlet_code and str(outlet_code).lower() != "all":
                sr_q["outlet_code"] = outlet_code
                
            sr_docs = list(db["hospital_salesreturn"].find(sr_q))
            sr_uhids = [str(s.get("uhid") or "").strip() for s in sr_docs if s.get("uhid")]
            patient_map = {}
            if sr_uhids:
                try:
                    p_docs = list(db["hospital_patient"].find({"$or": [{"uhid": {"$in": sr_uhids}}, {"patient_id": {"$in": sr_uhids}}]}))
                    for p in p_docs:
                        u1 = str(p.get("uhid") or "").strip()
                        u2 = str(p.get("patient_id") or "").strip()
                        pname = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or str(p.get("patient_name") or p.get("name") or "").strip()
                        if u1: patient_map[u1] = pname
                        if u2: patient_map[u2] = pname
                    missing_uhids = [u for u in sr_uhids if u not in patient_map]
                    if missing_uhids:
                        reg_docs = list(db["hospital_patientregistration"].find({"$or": [{"uhid": {"$in": missing_uhids}}, {"PatientId": {"$in": missing_uhids}}]}))
                        for pr in reg_docs:
                            uid = str(pr.get("uhid") or pr.get("PatientId") or "").strip()
                            fname = " ".join([x for x in [(pr.get("firstName") or "").strip(), (pr.get("middleName") or "").strip(), (pr.get("lastName") or "").strip()] if x]).strip()
                            if fname: patient_map[uid] = fname
                except Exception:
                    pass

            for sr in sr_docs:
                sr_amt = clean_num(sr.get("refund_amount") or sr.get("return_amount") or sr.get("total_amount") or sr.get("net_amount"))
                if sr_amt <= 0:
                    continue
                sr_date = sr.get("return_date") or sr.get("return_bill_date") or sr.get("created_date") or sr.get("paid_date") or sr.get("refund_datetime")
                dt_str = format_ist_datetime(sr_date) if sr_date else ""
                d_only = format_ist_date(sr_date) if sr_date else ""
                t_only = format_ist_time(sr_date) if sr_date else ""
                
                sr_no = str(sr.get("sales_return_number") or sr.get("return_no") or sr.get("return_bill_no") or (f"SR-{sr.get('bill_no')}" if sr.get('bill_no') else str(sr.get("_id"))[-8:]))
                orig_bno = str(sr.get("bill_no") or sr.get("original_bill_no") or "")
                u_val = str(sr.get("uhid") or "").strip()
                p_name = str(sr.get("patient_name") or sr.get("patientname") or patient_map.get(u_val) or "").strip()
                if not p_name or p_name == "-":
                    p_name = f"Patient ({u_val})" if u_val else "Walk-in Patient"
                
                c_id = str(sr.get("CashierID") or sr.get("pharmacist_id") or sr.get("created_by") or "")
                c_name = cashier_map.get(c_id, c_id)
                narr = f"Pharmacy Sales Return for Bill {orig_bno}" if orig_bno else "Pharmacy Sales Return"
                
                vouchers.append({
                    "voucher_no": sr_no,
                    "date": dt_str,
                    "voucher_date": d_only or (dt_str.split(" ")[0] if " " in dt_str else dt_str),
                    "voucher_time": t_only or (dt_str.split(" ", 1)[1] if " " in dt_str else ""),
                    "voucher_type": "Sales Return",
                    "account_head": "Sales Return",
                    "paid_to_or_received_from": p_name,
                    "amount": sr_amt,
                    "cashier_id": c_id,
                    "cashier_name": c_name,
                    "narration": narr,
                    "is_sales_return": True,
                    "original_bill_no": orig_bno
                })
                
            # Sort vouchers naturally by date and voucher_no
            import re
            def natural_voucher_sort(v):
                v_no = str(v.get("voucher_no") or "")
                parts = [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', v_no)]
                return (v.get("voucher_date") or "", parts)
            vouchers.sort(key=natural_voucher_sort)
                
            tot_receipts = round(sum(v["amount"] for v in vouchers if v["voucher_type"] == "Receipt"), 2)
            tot_payments = round(sum(v["amount"] for v in vouchers if v["voucher_type"] == "Payment"), 2)
            tot_sales_returns = round(sum(v["amount"] for v in vouchers if v.get("is_sales_return") or v["voucher_type"] == "Sales Return"), 2)
            tot_expenses = tot_payments
            net_sundry = round(tot_receipts - tot_payments - tot_sales_returns, 2)
            
            return Response({
                "success": True,
                "report_title": "Miscellaneous Payment Report",
                "date_range": {"from_date": str(f_d)[:10], "to_date": str(t_d)[:10]},
                "summary": {
                    "total_receipts": tot_receipts,
                    "total_payments": tot_payments,
                    "total_sales_returns": tot_sales_returns,
                    "total_expenses": tot_expenses,
                    "net_sundry_cash": net_sundry
                },
                "count": len(vouchers),
                "data": vouchers,
                "receipts": [v for v in vouchers if v["voucher_type"] == "Receipt"],
                "payments": [v for v in vouchers if v["voucher_type"] == "Payment"],
                "sales_returns": [v for v in vouchers if v.get("is_sales_return") or v["voucher_type"] == "Sales Return"]
            }, status=status.HTTP_200_OK)
        finally:
            client.close()
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def all_consolidated_bill_report_api(request):
    """
    All Consolidated Bill Report API.
    Unified register across all billing modules (Consultation/Billing, Investigation,
    Discharge, Pharmacy, Sales Return, Refunds) classified by status:
    Paid, Pending, Cancel, Return, Refund.
    """
    try:
        from concurrent.futures import ThreadPoolExecutor
        from datetime import datetime, timedelta
        from .core_ledger_engine import get_db, parse_date, clean_num, to_ist, AccountsLedgerEngine

        data = request.data if request.method == "POST" else request.query_params
        from_str = data.get("from_date") or data.get("start_date")
        to_str = data.get("to_date") or data.get("end_date")
        outlet_code = str(data.get("outlet_code") or data.get("outlet") or "all").strip()
        status_filter = str(data.get("bill_status") or data.get("status") or "all").strip().lower()
        module_filter = str(data.get("module") or data.get("category") or "all").strip().lower()
        search_q = str(data.get("search") or "").strip().lower()

        today_str = datetime.now().strftime("%Y-%m-%d")
        f_dt = parse_date(from_str or today_str) or parse_date(today_str)
        t_dt = parse_date(to_str or today_str, is_end=True) or parse_date(today_str, is_end=True)
        f_dt_utc = f_dt - timedelta(hours=5, minutes=30)
        t_dt_utc = t_dt - timedelta(hours=5, minutes=30)

        _, db, _ = get_db()

        def _fetch_billtypes():
            by_no, by_id = {}, {}
            for bt in db["hospital_billtype"].find({}, {"billTypeNo": 1, "bill_name": 1, "bill_type": 1}):
                nm = str(bt.get("bill_name") or "").strip()
                if not nm:
                    continue
                if bt.get("billTypeNo"):
                    by_no[str(bt["billTypeNo"]).strip()] = nm
                if bt.get("bill_type") is not None:
                    by_id[str(bt["bill_type"]).strip()] = nm
            return by_no, by_id

        def _outlet_q(q):
            if outlet_code.lower() != "all":
                q["outlet_code"] = outlet_code
            return q

        def _fetch_billing():
            q = _outlet_q({"billed_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}})
            return list(db["hospital_billing"].find(q, {
                "bill_number": 1, "bill_no": 1, "billed_date": 1, "created_date": 1,
                "uhid": 1, "patient_name": 1, "patientname": 1, "bill_type": 1,
                "total_fees": 1, "net_amount": 1, "discount_amount": 1, "discount": 1,
                "payment_method": 1, "payment_mode": 1, "payment_status": 1,
                "is_cancelled": 1, "is_active": 1, "cancelled_reason": 1, "outlet_code": 1
            }))

        def _fetch_invest():
            q = _outlet_q({"investBillDate": {"$gte": f_dt_utc, "$lte": t_dt_utc}})
            return list(db["hospital_investbilling"].find(q, {
                "investBillNo": 1, "bill_no": 1, "investBillDate": 1, "created_date": 1,
                "uhid": 1, "ipNumber": 1, "patient_name": 1, "patientname": 1,
                "billTypeNo": 1, "bill_type": 1, "finalPrice": 1, "total": 1, "discount": 1,
                "paymentMethod": 1, "payment_mode": 1, "paymentStatus": 1,
                "is_cancelled": 1, "is_active": 1, "cancelled_reason": 1, "outlet_code": 1
            }))

        def _fetch_discharge():
            q = _outlet_q({
                "bill_date": {"$gte": f_dt_utc, "$lte": t_dt_utc},
                "status": {"$ne": "Estimate"}
            })
            return list(db["hospital_dischargebilling"].find(q, {
                "bill_no": 1, "bill_number": 1, "insurance_bill_number": 1,
                "bill_date": 1, "discharge_date": 1, "uhid": 1, "ipNumber": 1, "ip_number": 1,
                "patient_name": 1, "patientname": 1, "total_amount": 1, "net_amount": 1,
                "discount_amount": 1, "payment_method": 1, "payment_mode": 1,
                "company_name": 1, "is_insurance_bill": 1, "status": 1,
                "is_cancelled": 1, "cancelled_reason": 1, "outlet_code": 1
            }))

        def _fetch_pharmacy():
            q = _outlet_q({
                "bill_date": {"$gte": f_dt_utc, "$lte": t_dt_utc},
                "billing_mode": {"$ne": "ESTIMATE"},
                "billing_status": {"$ne": "Estimate"}
            })
            return list(db["hospital_pharmacybilling"].find(q, {
                "bill_no": 1, "bill_date": 1, "uhid": 1, "inpatient_number": 1,
                "patientname": 1, "patient_name": 1, "total_amount": 1, "net_amount": 1,
                "overall_discount_amount": 1, "discount_amount": 1,
                "payment_mode": 1, "billing_mode": 1, "billing_status": 1,
                "is_deleted": 1, "delete_reason": 1, "outlet_code": 1
            }))

        def _fetch_sales_returns():
            q = _outlet_q({"$or": [
                {"created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
                {"return_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
            ]})
            return list(db["hospital_salesreturn"].find(q, {
                "return_bill_no": 1, "sales_return_number": 1, "return_no": 1, "bill_no": 1,
                "created_date": 1, "return_date": 1, "uhid": 1, "patient_name": 1, "patientName": 1,
                "return_amount": 1, "total_amount": 1, "net_amount": 1, "amount": 1,
                "PaymentType": 1, "payment_mode": 1, "reason": 1, "outlet_code": 1
            }))

        def _fetch_refunds():
            res_list = []
            for col_name, label in (
                ("hospital_refund", "Consultation / OP Refund"),
                ("hospital_investrefund", "Investigation Refund"),
                ("hospital_ipadvance_refund", "IP Advance Refund"),
            ):
                q = _outlet_q({"$or": [
                    {"created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
                    {"refund_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
                ]})
                for doc in db[col_name].find(q):
                    doc["_refund_source"] = label
                    res_list.append(doc)
            return res_list

        with ThreadPoolExecutor(max_workers=6) as executor:
            f_bt = executor.submit(_fetch_billtypes)
            f_b = executor.submit(_fetch_billing)
            f_i = executor.submit(_fetch_invest)
            f_d = executor.submit(_fetch_discharge)
            f_p = executor.submit(_fetch_pharmacy)
            f_sr = executor.submit(_fetch_sales_returns)
            f_rf = executor.submit(_fetch_refunds)

            bt_no_map, bt_id_map = f_bt.result()
            b_docs = f_b.result()
            i_docs = f_i.result()
            d_docs = f_d.result()
            p_docs = f_p.result()
            sr_docs = f_sr.result()
            rf_docs = f_rf.result()

        all_uhids = list({
            str(doc.get("uhid") or "").strip()
            for grp in (b_docs, i_docs, d_docs, p_docs, sr_docs, rf_docs)
            for doc in grp if doc.get("uhid")
        })
        p_map = {}
        if all_uhids:
            for p in db["hospital_patient"].find(
                {"uhid": {"$in": all_uhids}},
                {"uhid": 1, "firstName": 1, "lastName": 1, "patient_name": 1, "patientname": 1}
            ):
                uk = str(p.get("uhid") or "").strip()
                nm = str(p.get("patient_name") or p.get("patientname") or f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()).strip()
                if uk and nm:
                    p_map[uk] = nm

        def _fmt_dt(raw):
            dt = to_ist(raw)
            if isinstance(dt, datetime):
                return dt.strftime("%d/%m/%Y %I:%M %p"), dt.strftime("%Y-%m-%d %H:%M:%S")
            return str(raw or ""), str(raw or "")

        rows = []

        # 1. Billing / Consultation
        for b in b_docs:
            bno = str(b.get("bill_number") or b.get("bill_no") or "").strip()
            if not bno:
                continue
            is_cancel = bool(b.get("is_cancelled") or b.get("is_active") is False)
            p_stat = str(b.get("payment_status") or "").strip().lower()
            p_meth = str(b.get("payment_method") or b.get("payment_mode") or "Cash").strip()
            if is_cancel:
                bill_status = "Cancel"
            elif p_stat == "pending" or (p_meth.lower() == "credit" and p_stat != "paid"):
                bill_status = "Credit Pending" if "credit" in p_meth.lower() else "Cash Pending"
            else:
                bill_status = "Paid"

            net = clean_num(b.get("total_fees") or b.get("net_amount"))
            disc = clean_num(b.get("discount_amount") or b.get("discount"))
            gross = round(net + disc, 2)
            uhid = str(b.get("uhid") or "").strip()
            pname = str(b.get("patient_name") or b.get("patientname") or p_map.get(uhid) or "Patient").strip()
            dt_disp, dt_sort = _fmt_dt(b.get("billed_date") or b.get("created_date"))
            cat = bt_id_map.get(str(b.get("bill_type") or "").strip()) or "Consultation / Registration"
            rows.append({
                "bill_no": bno,
                "date": dt_disp,
                "_sort": dt_sort,
                "module": "Billing",
                "category": cat,
                "uhid": uhid or "—",
                "ip_number": "—",
                "patient_name": pname,
                "payment_mode": p_meth,
                "gross_amount": gross,
                "discount_amount": round(disc, 2),
                "net_amount": round(net, 2),
                "status": bill_status,
                "remarks": str(b.get("cancelled_reason") or "").strip(),
                "outlet_code": b.get("outlet_code") or "",
            })

        # 2. Investigation Billing
        for inv in i_docs:
            bno = str(inv.get("investBillNo") or inv.get("bill_no") or "").strip()
            if not bno:
                continue
            is_cancel = bool(inv.get("is_cancelled") or inv.get("is_active") is False)
            p_stat = str(inv.get("paymentStatus") or "").strip().lower()
            p_meth = str(inv.get("paymentMethod") or inv.get("payment_mode") or "Cash").strip()
            if is_cancel:
                bill_status = "Cancel"
            elif p_stat == "pending" or (p_meth.lower() == "credit" and p_stat != "paid"):
                bill_status = "Credit Pending" if "credit" in p_meth.lower() else "Cash Pending"
            else:
                bill_status = "Paid"

            net = clean_num(inv.get("finalPrice") or inv.get("total"))
            disc = clean_num(inv.get("discount"))
            gross = round(net + disc, 2)
            uhid = str(inv.get("uhid") or "").strip()
            pname = str(inv.get("patient_name") or inv.get("patientname") or p_map.get(uhid) or "Patient").strip()
            dt_disp, dt_sort = _fmt_dt(inv.get("investBillDate") or inv.get("created_date"))
            cat = bt_no_map.get(str(inv.get("billTypeNo") or "").strip()) or bt_id_map.get(str(inv.get("bill_type") or "").strip()) or "Investigation"
            rows.append({
                "bill_no": bno,
                "date": dt_disp,
                "_sort": dt_sort,
                "module": "Investigation",
                "category": cat,
                "uhid": uhid or "—",
                "ip_number": str(inv.get("ipNumber") or "—").strip() or "—",
                "patient_name": pname,
                "payment_mode": p_meth,
                "gross_amount": gross,
                "discount_amount": round(disc, 2),
                "net_amount": round(net, 2),
                "status": bill_status,
                "remarks": str(inv.get("cancelled_reason") or "").strip(),
                "outlet_code": inv.get("outlet_code") or "",
            })

        # 3. Discharge Billing
        for dis in d_docs:
            bno = str(dis.get("bill_no") or dis.get("bill_number") or "").strip()
            if not bno:
                continue
            st_l = str(dis.get("status") or "").strip().lower()
            is_cancel = bool(dis.get("is_cancelled") or st_l == "cancelled")
            p_meth = str(dis.get("payment_method") or dis.get("payment_mode") or "Cash").strip()
            is_ins = bool(dis.get("is_insurance_bill") or p_meth.lower() == "credit")
            if is_cancel:
                bill_status = "Cancel"
            elif st_l == "paid":
                bill_status = "Paid"
            elif is_ins or st_l == "pending":
                bill_status = "Credit Pending" if "credit" in p_meth.lower() else "Cash Pending"
            else:
                bill_status = "Paid"

            tot = clean_num(dis.get("total_amount"))
            net = clean_num(dis.get("net_amount"))
            disc = clean_num(dis.get("discount_amount"))
            gross = tot if tot > 0 else round(net + disc, 2)
            uhid = str(dis.get("uhid") or "").strip()
            pname = str(dis.get("patient_name") or dis.get("patientname") or p_map.get(uhid) or "Patient").strip()
            dt_disp, dt_sort = _fmt_dt(dis.get("bill_date") or dis.get("discharge_date"))
            comp = str(dis.get("company_name") or "").strip()
            pm_disp = f"{p_meth} ({comp})" if comp else p_meth
            rows.append({
                "bill_no": bno,
                "date": dt_disp,
                "_sort": dt_sort,
                "module": "Discharge",
                "category": "DISCHARGE",
                "uhid": uhid or "—",
                "ip_number": str(dis.get("ipNumber") or dis.get("ip_number") or "—").strip() or "—",
                "patient_name": pname,
                "payment_mode": pm_disp,
                "gross_amount": round(gross, 2),
                "discount_amount": round(disc, 2),
                "net_amount": round(net if net > 0 else gross, 2),
                "status": bill_status,
                "remarks": str(dis.get("cancelled_reason") or dis.get("insurance_bill_number") or "").strip(),
                "outlet_code": dis.get("outlet_code") or "",
            })

        # 4. Pharmacy Billing
        for pb in p_docs:
            bno = str(pb.get("bill_no") or "").strip()
            if not bno:
                continue
            b_stat = str(pb.get("billing_status") or "").strip().lower()
            is_cancel = bool(pb.get("is_deleted") or b_stat in ("cancelled", "deleted"))
            p_meth = str(pb.get("payment_mode") or pb.get("billing_mode") or "Cash").strip()
            if is_cancel:
                bill_status = "Cancel"
            elif b_stat == "pending" or (str(pb.get("billing_mode") or "").upper() == "IP CREDIT" and b_stat != "paid"):
                is_cred = "credit" in p_meth.lower() or str(pb.get("billing_mode") or "").upper() == "IP CREDIT"
                bill_status = "Credit Pending" if is_cred else "Cash Pending"
            else:
                bill_status = "Paid"

            net = clean_num(pb.get("net_amount") or pb.get("total_amount"))
            disc = clean_num(pb.get("overall_discount_amount") or pb.get("discount_amount"))
            gross = round(net + disc, 2)
            uhid = str(pb.get("uhid") or "").strip()
            pname = str(pb.get("patientname") or pb.get("patient_name") or p_map.get(uhid) or "Pharmacy Patient").strip()
            dt_disp, dt_sort = _fmt_dt(pb.get("bill_date"))
            rows.append({
                "bill_no": bno,
                "date": dt_disp,
                "_sort": dt_sort,
                "module": "Pharmacy",
                "category": f"PHARMACY ({pb.get('billing_mode') or 'DIRECT'})",
                "uhid": uhid or "—",
                "ip_number": str(pb.get("inpatient_number") or "—").strip() or "—",
                "patient_name": pname,
                "payment_mode": p_meth,
                "gross_amount": gross,
                "discount_amount": round(disc, 2),
                "net_amount": round(net, 2),
                "status": bill_status,
                "remarks": str(pb.get("delete_reason") or "").strip(),
                "outlet_code": pb.get("outlet_code") or "",
            })

        # 5. Sales Returns
        for sr in sr_docs:
            bno = str(sr.get("return_bill_no") or sr.get("sales_return_number") or sr.get("return_no") or sr.get("bill_no") or "").strip()
            if not bno:
                continue
            amt = abs(clean_num(sr.get("return_amount") or sr.get("total_amount") or sr.get("net_amount") or sr.get("amount")))
            uhid = str(sr.get("uhid") or "").strip()
            pname = str(sr.get("patient_name") or sr.get("patientName") or p_map.get(uhid) or "Sales Return").strip()
            dt_disp, dt_sort = _fmt_dt(sr.get("created_date") or sr.get("return_date"))
            rows.append({
                "bill_no": bno,
                "date": dt_disp,
                "_sort": dt_sort,
                "module": "Sales Return",
                "category": "SALES RETURN",
                "uhid": uhid or "—",
                "ip_number": "—",
                "patient_name": pname,
                "payment_mode": str(sr.get("PaymentType") or sr.get("payment_mode") or "Cash").strip(),
                "gross_amount": round(amt, 2),
                "discount_amount": 0.0,
                "net_amount": round(amt, 2),
                "status": "Return",
                "remarks": f"Orig Bill: {sr.get('bill_no') or '-'} {sr.get('reason') or ''}".strip(),
                "outlet_code": sr.get("outlet_code") or "",
            })

        # 6. Refunds
        for rf in rf_docs:
            bno = str(rf.get("refund_no") or rf.get("bill_no") or rf.get("bill_number") or rf.get("investBillNo") or "").strip() or "-"
            amt = abs(clean_num(rf.get("refund_amount") or rf.get("amount") or rf.get("total_amount")))
            uhid = str(rf.get("uhid") or "").strip()
            pname = str(rf.get("patient_name") or rf.get("patientname") or p_map.get(uhid) or "Refund Patient").strip()
            dt_disp, dt_sort = _fmt_dt(rf.get("created_date") or rf.get("refund_date"))
            rows.append({
                "bill_no": bno,
                "date": dt_disp,
                "_sort": dt_sort,
                "module": "Refund",
                "category": str(rf.get("_refund_source") or "REFUND").upper(),
                "uhid": uhid or "—",
                "ip_number": str(rf.get("ipNumber") or rf.get("ip_number") or "—").strip() or "—",
                "patient_name": pname,
                "payment_mode": str(rf.get("payment_mode") or rf.get("payment_method") or "Cash").strip(),
                "gross_amount": round(amt, 2),
                "discount_amount": 0.0,
                "net_amount": round(amt, 2),
                "status": "Refund",
                "remarks": str(rf.get("reason") or rf.get("remarks") or "").strip(),
                "outlet_code": rf.get("outlet_code") or "",
            })

        # Compute global summary before status/module filters
        status_summary = {
            s: {"count": 0, "amount": 0.0}
            for s in ("Paid", "Cash Pending", "Credit Pending", "Cancel", "Return", "Refund")
        }
        credit_bills_amt = 0.0
        credit_paid_amt = 0.0
        actual_billed_amt = 0.0

        for r in rows:
            st = r["status"]
            net_v = clean_num(r.get("net_amount"))
            gross_v = clean_num(r.get("gross_amount"))
            pm_l = str(r.get("payment_mode") or "").lower()
            if st in status_summary:
                status_summary[st]["count"] += 1
                status_summary[st]["amount"] = round(status_summary[st]["amount"] + net_v, 2)

            if st == "Paid":
                actual_billed_amt += net_v
                if "credit" in pm_l:
                    credit_paid_amt += net_v
                    credit_bills_amt += gross_v
            elif st == "Credit Pending":
                actual_billed_amt += net_v
                credit_bills_amt += gross_v
            elif st == "Cash Pending":
                actual_billed_amt += net_v

        # Reconcile Cash, Bank, Sales Return/Refund, Expense, and Net Cash strictly with 3-Tier Ledger Engine
        ledger_res = AccountsLedgerEngine.get_ledger_data(
            from_str=from_str or today_str,
            to_str=to_str or today_str,
            outlet_code=outlet_code,
        )
        l_bills = ledger_res.get("bills", [])
        l_gross_cash = 0.0
        l_bank = 0.0
        l_credit_coll = 0.0
        l_sales_ret = 0.0
        l_expenses = 0.0
        for lb in l_bills:
            l_cat = str(lb.get("category") or "").lower()
            is_sr = bool(lb.get("is_sales_return") or "return" in l_cat or "refund" in l_cat or clean_num(lb.get("sales_return")) > 0)
            is_exp = bool(lb.get("is_expense") or "expense" in l_cat or "payment" in l_cat)
            l_amt = abs(clean_num(lb.get("amount") or lb.get("gross") or lb.get("net_amount")))
            if is_sr:
                l_sales_ret += abs(clean_num(lb.get("sales_return_amount") or lb.get("refund_amount") or l_amt))
            elif is_exp:
                l_expenses += abs(clean_num(lb.get("expense_amount") or l_amt))
            else:
                l_gross_cash += clean_num(lb.get("cash"))
                l_bank += clean_num(lb.get("bank"))
                l_credit_coll += clean_num(lb.get("credit"))

        l_net_cash = round(l_gross_cash - l_sales_ret - l_expenses, 2)
        credit_pending_amt = round(status_summary["Credit Pending"]["amount"], 2)
        financial_summary = {
            "gross_cash": round(l_gross_cash, 2),
            "bank": round(l_bank, 2),
            "sales_return_refund": round(l_sales_ret, 2),
            "expenses_paid": round(l_expenses, 2),
            "net_cash": l_net_cash,
            "counter_credit": round(l_credit_coll, 2),
            "credit_amount": round(l_credit_coll, 2),
            "credit_bills_amount": round(credit_bills_amt, 2),
            "actual_billed_amount": round(actual_billed_amt, 2),
            "cash_pending_amount": round(status_summary["Cash Pending"]["amount"], 2),
            "credit_pending_amount": credit_pending_amt,
            "cancel_amount": round(status_summary["Cancel"]["amount"], 2),
        }

        # Apply filters
        filtered = []
        for r in rows:
            if status_filter != "all" and r["status"].lower() != status_filter:
                continue
            if module_filter != "all" and r["module"].lower() != module_filter and r["category"].lower() != module_filter:
                continue
            if search_q:
                hay = f"{r['bill_no']} {r['uhid']} {r['ip_number']} {r['patient_name']} {r['category']} {r['payment_mode']} {r['status']}".lower()
                if search_q not in hay:
                    continue
            filtered.append(r)

        filtered.sort(key=lambda x: (x["_sort"], x["bill_no"]), reverse=True)
        for idx, r in enumerate(filtered, start=1):
            r["sl_no"] = idx
            r.pop("_sort", None)

        return Response({
            "success": True,
            "report_title": "All Consolidated Bill Report",
            "date_range": {"from_date": str(f_dt)[:10], "to_date": str(t_dt)[:10]},
            "summary": {
                "total_count": len(rows),
                "filtered_count": len(filtered),
                "filtered_amount": round(sum(r["net_amount"] for r in filtered), 2),
                "by_status": status_summary,
                "financial_summary": financial_summary,
            },
            "data": filtered,
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
