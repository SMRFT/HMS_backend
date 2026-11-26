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
