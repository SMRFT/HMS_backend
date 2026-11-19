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

        res = AccountsLedgerEngine.get_ledger_data(
            from_str=from_f,
            to_str=to_f,
            outlet_code=outlet_code
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

        # Build Bill Type Master Map
        billtype_map = {}
        try:
            for bt in db["hospital_billtype"].find({"is_active": {"$ne": False}}):
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
            
            # 1. Edit History from Registration
            b_edits = list(db["hospital_billing"].find({"edit_history": {"$exists": True, "$ne": []}}))
            for b in b_edits:
                for eh in (b.get("edit_history") or []):
                    if not isinstance(eh, dict): continue
                    dt_s = format_ist_date(eh.get("edited_date") or b.get("billed_date"))
                    if f_d and dt_s < str(f_d)[:10]: continue
                    if t_d and dt_s > str(t_d)[:10]: continue

                    req_id = eh.get("requested_by") or b.get("created_by") or ""
                    appr_id = eh.get("edited_by_name") or eh.get("edited_by") or b.get("lastmodified_by") or "STAFF"
                    req_name = resolve_created_by_name(req_id) or "Registration Staff"
                    appr_name = resolve_created_by_name(appr_id) or "Admin"

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
                        "billing_details": b.get("items") or [{"name": "Registration Fee Modification", "amount": clean_num(b.get("total_fees"))}]
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

            inv_refund_docs = list(db["hospital_investrefund"].find({"$and": ir_base}))
            
            # Pre-fetch original hospital_investbilling for these refunds
            inv_orig_nos = [str(r.get("investBillNo") or "").strip() for r in inv_refund_docs if r.get("investBillNo")]
            inv_orig_map = {}
            if inv_orig_nos:
                for ib in db["hospital_investbilling"].find({"investBillNo": {"$in": inv_orig_nos}}):
                    inv_orig_map[str(ib.get("investBillNo")).strip()] = ib

            for ir in inv_refund_docs:
                orig_bno = str(ir.get("investBillNo") or "").strip()
                inv_b = inv_orig_map.get(orig_bno, {})

                bt_no = ir.get("billTypeNo") or inv_b.get("billTypeNo") or "INVEST"
                bt_name = billtype_map.get(str(bt_no).strip()) or bt_no

                req_id = ir.get("requested_by") or ir.get("created_by") or ""
                appr_id = ir.get("approved_by") or ir.get("lastmodified_by") or ir.get("CashierID") or ""
                req_name = resolve_created_by_name(req_id) or "Lab / Staff"
                appr_name = resolve_created_by_name(appr_id) or "Cashier"

                ret_amt = clean_num(ir.get("refund_finalPrice") or ir.get("refund_amount") or 0.0)
                orig_amt = clean_num(inv_b.get("finalPrice") or inv_b.get("total") or ret_amt)

                dt_val = ir.get("refundBillDate") or ir.get("paid_date") or ir.get("created_date") or ir.get("investBillDate")
                dt_str = format_ist_date(dt_val)

                raw_items = ir.get("item") or ir.get("items") or []
                item_details = []
                for it in (raw_items if isinstance(raw_items, list) else []):
                    if isinstance(it, dict):
                        item_details.append({
                            "name": it.get("itemName") or it.get("test_name") or "Investigation Test",
                            "quantity": it.get("quantity") or 1,
                            "price": clean_num(it.get("price") or it.get("rate") or 0.0),
                            "billTypeNo": it.get("billTypeNo") or bt_no
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
                    
            # 3. Include all verified bills under proper billing source
            invest_code_prefixes = [
                "USG", "LAB", "XRAY", "X-RAY", "CT", "MRI", "ECHO", "ECG",
                "CAR", "CLL", "COS", "DEN", "DIA", "HC", "INSR", "TMT", "RADIO", "DIAG"
            ]

            for b in res["bills"]:
                cat = str(b.get("category", "")).upper()
                b_no = str(b.get("bill_no", "")).strip()

                is_invest = (
                    b.get("is_investigation") is True or
                    "INVEST" in cat or
                    any(pfx in cat for pfx in invest_code_prefixes) or
                    any(b_no.startswith(pfx) for pfx in ["26279", "26273", "26278", "262710", "262706"])
                )
                is_return = (
                    "RETURN" in cat or
                    "REFUND" in cat or
                    b.get("is_return") is True or
                    b.get("is_refund") is True
                )
                is_pharm = "PHARM" in cat

                if is_return:
                    src = "Sales Return"
                elif is_pharm:
                    src = "Pharmacy Billing"
                elif is_invest:
                    src = "Investigation Billing"
                else:
                    src = "Registration Billing"
                    
                by_source[src] = by_source.get(src, 0) + 1
                gross_amt = clean_num(b.get("gross") or b.get("total_amount") or b.get("amount") or 0.0)
                net_amt = clean_num(b.get("net_amount") or b.get("cash") or b.get("amount") or 0.0)
                old_val = str(round(gross_amt, 2)) if gross_amt != 0 else str(round(net_amt, 2))
                new_val = str(round(net_amt, 2))

                # Resolve requested_by and approved_by properly
                req_raw = b.get("created_by") or b.get("doctor") or "Staff"
                appr_raw = b.get("lastmodified_by") or b.get("cashier_name") or b.get("cashier_id") or "Counter Staff"

                req_name = resolve_created_by_name(req_raw) or "Staff"
                appr_name = resolve_created_by_name(appr_raw) or "Counter Staff"

                bt_label = b.get("bill_type_name") or b.get("category") or src

                audit_rows.append({
                    "source": src,
                    "bill_type": bt_label,
                    "record_no": b.get("bill_no"),
                    "original_bill_no": b.get("bill_no"),
                    "uhid": b.get("uhid") or b.get("mr_no") or "",
                    "patient_name": b.get("patient_name") or "Patient",
                    "description": f"Verified {b.get('payment_mode', 'CASH')} collection for {b.get('category')}",
                    "old_value": old_val,
                    "new_value": new_val,
                    "requested_by": req_name,
                    "requested_by_id": str(req_raw),
                    "approved_by": appr_name,
                    "approved_by_id": str(appr_raw),
                    "edited_by_name": appr_name,
                    "edited_date": b.get("date"),
                    "is_approved": True,
                    "billing_details": b.get("particulars") or []
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
