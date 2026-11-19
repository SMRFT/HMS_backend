"""
Cluster 6: Inventory & Stock Auditing APIs
==========================================
1. IP / OP Stock Movement Report
2. Sales Return Report
Direct MongoDB queries via get_db() ensuring zero latency and 100% data fidelity.
"""

from datetime import datetime, timedelta
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from .core_ledger_engine import AccountsLedgerEngine, clean_num, parse_date, get_db
from hospital.Views.dbcollection import resolve_created_by_name

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def ip_op_stock_movement_api(request):
    """
    Dedicated IP vs OP Stock Movement / Consumption Audit API.
    Audits dispensary items issued to inpatients vs outpatients with quantities and values.
    """
    client = None
    try:
        data = request.data if request.method == "POST" else request.query_params
        from_f = data.get("from_date") or data.get("start_date")
        to_f = data.get("to_date") or data.get("end_date")
        outlet_code = data.get("outlet_code") or data.get("outlet")

        f_date = parse_date(from_f) if from_f else None
        t_date = parse_date(to_f, is_end=True) if to_f else None

        client, db, g_db = get_db()
        q = {}
        if f_date and t_date:
            f_utc = f_date - timedelta(hours=5, minutes=30)
            t_utc = t_date - timedelta(hours=5, minutes=30)
            q["$or"] = [
                {"bill_date": {"$gte": f_utc, "$lte": t_utc}},
                {"created_date": {"$gte": f_utc, "$lte": t_utc}},
                {"created_at": {"$gte": f_utc, "$lte": t_utc}}
            ]
        elif f_date:
            f_utc = f_date - timedelta(hours=5, minutes=30)
            q["$or"] = [
                {"bill_date": {"$gte": f_utc}},
                {"created_date": {"$gte": f_utc}}
            ]
        elif t_date:
            t_utc = t_date - timedelta(hours=5, minutes=30)
            q["$or"] = [
                {"bill_date": {"$lte": t_utc}},
                {"created_date": {"$lte": t_utc}}
            ]

        if outlet_code and outlet_code.lower() != "all":
            q["outlet_code"] = outlet_code

        bills = list(db["hospital_pharmacybilling"].find(q, {
            "bill_no": 1,
            "bill_date": 1,
            "inpatient_number": 1,
            "medicine_particulars": 1,
            "outlet_code": 1
        }))

        # Collect unique item_ids for name enrichment
        item_ids = set()
        for b in bills:
            for med in (b.get("medicine_particulars") or []):
                if isinstance(med, dict) and med.get("item_id") is not None:
                    try:
                        item_ids.add(int(med["item_id"]))
                    except (TypeError, ValueError):
                        pass

        item_name_map = {}
        if item_ids:
            for itm in db["hospital_pharmacyitem"].find({"item_id": {"$in": list(item_ids)}}, {"item_id": 1, "item_name": 1}):
                item_name_map[itm["item_id"]] = itm.get("item_name")

        item_stats = {}
        for b in bills:
            ip_val = b.get("inpatient_number")
            is_ip = bool(ip_val and str(ip_val).strip() and str(ip_val).strip() != "-")
            for med in (b.get("medicine_particulars") or []):
                if not isinstance(med, dict):
                    continue
                try:
                    iid = int(med.get("item_id"))
                except (TypeError, ValueError):
                    continue

                qty_val = (
                    med.get("qty") if med.get("qty") is not None else
                    med.get("quantity") if med.get("quantity") is not None else
                    med.get("Issued_Qty") if med.get("Issued_Qty") is not None else
                    med.get("issued_quantity") if med.get("issued_quantity") is not None else
                    med.get("unit_quantity") if med.get("unit_quantity") is not None else
                    med.get("count", 0)
                )
                amt_val = (
                    med.get("calculated_price") if med.get("calculated_price") is not None else
                    med.get("amount") if med.get("amount") is not None else
                    med.get("total_amount") if med.get("total_amount") is not None else
                    med.get("net_amount") if med.get("net_amount") is not None else
                    med.get("price", 0)
                )
                qty = clean_num(qty_val)
                amt = clean_num(amt_val)
                item_name = med.get("item_name") or med.get("itemName") or med.get("medicine_name") or item_name_map.get(iid) or f"Item #{iid}"
                
                bucket = item_stats.setdefault(iid, {
                    "item_id": iid,
                    "item_name": item_name,
                    "ip_qty": 0.0,
                    "ip_amount": 0.0,
                    "op_qty": 0.0,
                    "op_amount": 0.0
                })
                if is_ip:
                    bucket["ip_qty"] += qty
                    bucket["ip_amount"] += amt
                else:
                    bucket["op_qty"] += qty
                    bucket["op_amount"] += amt

        rows = list(item_stats.values())
        for r in rows:
            tot_q = r["ip_qty"] + r["op_qty"]
            tot_a = r["ip_amount"] + r["op_amount"]
            r["total_qty"] = round(tot_q, 2)
            r["ip_qty"] = round(r["ip_qty"], 2)
            r["op_qty"] = round(r["op_qty"], 2)
            r["ip_amount"] = round(r["ip_amount"], 2)
            r["op_amount"] = round(r["op_amount"], 2)
            r["total_amount"] = round(tot_a, 2)

        rows.sort(key=lambda x: x["total_amount"], reverse=True)

        summary = {
            "total_items": len(rows),
            "total_ip_qty": round(sum(r["ip_qty"] for r in rows), 2),
            "total_ip_amount": round(sum(r["ip_amount"] for r in rows), 2),
            "total_op_qty": round(sum(r["op_qty"] for r in rows), 2),
            "total_op_amount": round(sum(r["op_amount"] for r in rows), 2),
            "grand_total_qty": round(sum(r["total_qty"] for r in rows), 2),
            "grand_total_amount": round(sum(r["total_amount"] for r in rows), 2),
        }

        return Response({
            "success": True,
            "report_title": "IP / OP Stock Movement Report",
            "date_range": {"from_date": from_f, "to_date": to_f},
            "summary": summary,
            "data": rows
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass


@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def sales_return_report_api(request):
    """
    Dedicated Sales Return & Refund Report API.
    Audits returns and refunds across:
    1. Pharmacy Sales Returns (hospital_salesreturn)
    2. Investigation Refunds (hospital_investrefund linked to hospital_investbilling with is_approved: True)
    Checks bill types properly and displays requested_by, approved_by, and itemized billing details.
    """
    client = None
    try:
        data = request.data if request.method == "POST" else request.query_params
        from_f = data.get("from_date") or data.get("start_date")
        to_f = data.get("to_date") or data.get("end_date")
        outlet_code = data.get("outlet_code") or data.get("outlet")
        bill_type_filter = str(data.get("bill_type") or data.get("return_type") or "all").strip().lower()

        f_date = parse_date(from_f) if from_f else None
        t_date = parse_date(to_f, is_end=True) if to_f else None

        client, db, g_db = get_db()

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

        # ── 1. Pharmacy Sales Returns Query ──────────────────────────────────
        q_pharm = {}
        if f_date and t_date:
            f_utc = f_date - timedelta(hours=5, minutes=30)
            t_utc = t_date - timedelta(hours=5, minutes=30)
            f_str = f_date.strftime("%Y-%m-%d")
            t_str = t_date.strftime("%Y-%m-%d")
            q_pharm["$or"] = [
                {"return_bill_date": {"$gte": f_utc, "$lte": t_utc}},
                {"created_date": {"$gte": f_utc, "$lte": t_utc}},
                {"return_date": {"$gte": f_utc, "$lte": t_utc}},
                {"created_date": {"$gte": f_str, "$lte": t_str + " 23:59:59"}},
                {"return_bill_date": {"$gte": f_str, "$lte": t_str + " 23:59:59"}}
            ]
        if outlet_code and outlet_code.lower() != "all":
            q_pharm["outlet_code"] = outlet_code

        # Status filter
        status_filter = data.get("status")
        if status_filter and status_filter.lower() == "paid":
            q_pharm["$or"] = q_pharm.get("$or", []) + [
                {"status": {"$regex": "^paid$", "$options": "i"}},
                {"status": None},
                {"status": {"$exists": False}},
                {"status": ""},
                {"status": "Completed"}
            ]
        elif status_filter and status_filter.lower() == "pending":
            q_pharm["status"] = {"$regex": "^pending$", "$options": "i"}
        else:
            q_pharm["status"] = {"$ne": "Cancelled"}

        returns_list = []
        if bill_type_filter in ["all", "pharmacy", "pharmacy return", "pharmacy returns"]:
            returns_list = list(db["hospital_salesreturn"].find(q_pharm))

        # ── 2. Investigation Refunds Query ───────────────────────────────────
        invest_refunds_list = []
        if bill_type_filter not in ["pharmacy", "pharmacy return", "pharmacy returns"]:
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
            if f_date and t_date:
                f_utc = f_date - timedelta(hours=5, minutes=30)
                t_utc = t_date - timedelta(hours=5, minutes=30)
                f_str = f_date.strftime("%Y-%m-%d")
                t_str = t_date.strftime("%Y-%m-%d")
                ir_base.append({"$or": [
                    {"refundBillDate": {"$gte": f_utc, "$lte": t_utc}},
                    {"paid_date": {"$gte": f_utc, "$lte": t_utc}},
                    {"created_date": {"$gte": f_utc, "$lte": t_utc}},
                    {"investBillDate": {"$gte": f_utc, "$lte": t_utc}},
                    {"refund_datetime": {"$gte": f_str, "$lte": t_str + " 23:59:59"}},
                    {"paid_at": {"$gte": f_str, "$lte": t_str + " 23:59:59"}}
                ]})
            if outlet_code and outlet_code.lower() != "all":
                ir_base.append({"outlet_code": outlet_code})

            q_ir = {"$and": ir_base}
            invest_refunds_list = list(db["hospital_investrefund"].find(q_ir))

        # Pre-fetch original hospital_investbilling for investigation refunds
        invest_bill_nos = [str(r.get("investBillNo") or "").strip() for r in invest_refunds_list if r.get("investBillNo")]
        invest_bill_map = {}
        if invest_bill_nos:
            for ib in db["hospital_investbilling"].find({"investBillNo": {"$in": invest_bill_nos}}):
                invest_bill_map[str(ib.get("investBillNo")).strip()] = ib

        # Patient Name Lookup
        uhids = set()
        for r in returns_list:
            if r.get("uhid"): uhids.add(str(r.get("uhid")).strip())
        for ir in invest_refunds_list:
            if ir.get("uhid"): uhids.add(str(ir.get("uhid")).strip())

        patient_map = {}
        if uhids and db is not None:
            pt_cursor = db["hospital_patient"].find(
                {"uhid": {"$in": list(uhids)}},
                {"uhid": 1, "firstName": 1, "middleName": 1, "lastName": 1, "patient_name": 1}
            )
            for p in pt_cursor:
                fn = (p.get("firstName") or "").strip()
                mn = (p.get("middleName") or "").strip()
                ln = (p.get("lastName") or "").strip()
                nm = " ".join([x for x in [fn, mn, ln] if x]).strip() or p.get("patient_name") or ""
                patient_map[str(p.get("uhid")).strip()] = nm

            missing_uhids = [u for u in uhids if u not in patient_map]
            if missing_uhids:
                for p in db["hospital_patientregistration"].find({"PatientId": {"$in": missing_uhids}}, {"PatientId": 1, "firstName": 1, "lastName": 1}):
                    fn = (p.get("firstName") or "").strip()
                    ln = (p.get("lastName") or "").strip()
                    nm = " ".join([x for x in [fn, ln] if x]).strip()
                    patient_map[str(p.get("PatientId")).strip()] = nm

        records = []
        tot_amount = 0.0
        tot_pharmacy = 0.0
        tot_invest = 0.0
        tot_cash = 0.0
        tot_card = 0.0
        tot_credit = 0.0

        # Process Pharmacy Sales Returns
        for r in returns_list:
            ret_amt = clean_num(r.get("return_amount") or r.get("total_amount") or 0.0)
            tot_amount += ret_amt
            tot_pharmacy += ret_amt
            pt_name = r.get("patient_name") or patient_map.get(str(r.get("uhid") or "").strip(), "") or "General"
            pmode = str(r.get("PaymentType") or r.get("payment_type") or "Cash").strip()

            if any(k in pmode.lower() for k in ["card", "upi", "online", "bank"]):
                tot_card += ret_amt
            elif "credit" in pmode.lower():
                tot_credit += ret_amt
            else:
                tot_cash += ret_amt

            dt_val = r.get("return_bill_date") or r.get("created_date") or r.get("return_date")
            if isinstance(dt_val, datetime):
                ist_dt = dt_val + timedelta(hours=5, minutes=30)
                dt_str = ist_dt.strftime("%d/%m/%Y %I:%M %p")
            else:
                dt_str = str(dt_val or "")[:19]

            particulars = r.get("medicine_particulars") or r.get("returned_items") or []
            if not isinstance(particulars, list):
                particulars = []

            # Format itemized details
            item_details = []
            for it in particulars:
                if isinstance(it, dict):
                    iname = it.get("item_name") or it.get("itemName") or f"Item #{it.get('item_id', '')}"
                    iqty = it.get("return_qty") or it.get("quantity") or 1
                    irate = clean_num(it.get("unit_price") or it.get("rate") or it.get("price") or 0.0)
                    iamt = clean_num(it.get("total_amount") or it.get("amount") or (irate * clean_num(iqty)))
                    item_details.append({
                        "item_name": iname,
                        "quantity": iqty,
                        "unit_price": irate,
                        "amount": iamt,
                        "batch": it.get("batch_no") or it.get("batch") or ""
                    })

            req_by_id = r.get("created_by") or r.get("pharmacist_id") or ""
            appr_by_id = r.get("approved_by") or r.get("lastmodified_by") or r.get("pharmacist_id") or r.get("created_by") or ""

            records.append({
                "return_bill_no": r.get("return_bill_no") or r.get("return_no") or r.get("sales_return_number") or str(r.get("_id")),
                "return_bill_date": dt_str,
                "original_bill_no": r.get("bill_no") or r.get("Bill_id") or "-",
                "bill_type": "Pharmacy Return",
                "bill_type_code": "PHARM",
                "bill_type_label": "Pharmacy Return",
                "category": "Pharmacy Return",
                "uhid": r.get("uhid") or "-",
                "inpatient_number": r.get("inpatient_number") or "-",
                "patient_name": pt_name,
                "return_amount": ret_amt,
                "amount": ret_amt,
                "payment_type": pmode,
                "requested_by": resolve_created_by_name(req_by_id) or "Pharmacy Staff",
                "requested_by_id": str(req_by_id),
                "approved_by": resolve_created_by_name(appr_by_id) or "Pharmacist",
                "approved_by_id": str(appr_by_id),
                "pharmacist_id": r.get("pharmacist_id") or r.get("created_by") or "",
                "status": r.get("status") or "Paid",
                "is_approved": True,
                "outlet_code": r.get("outlet_code") or "OLET002",
                "items_count": len(particulars),
                "medicine_particulars": particulars,
                "billing_details": item_details
            })

        # Process Investigation Refunds (hospital_investrefund linked to hospital_investbilling)
        for ir in invest_refunds_list:
            ret_amt = clean_num(ir.get("refund_finalPrice") or ir.get("refund_amount") or ir.get("amount") or 0.0)
            tot_amount += ret_amt
            tot_invest += ret_amt
            pt_name = patient_map.get(str(ir.get("uhid") or "").strip()) or ir.get("patientName") or "Patient"

            pd = ir.get("payment_details") or {}
            pmode = str(pd.get("method") or ir.get("paymentMethod") or ir.get("payment_method") or "Cash").strip()

            if any(k in pmode.lower() for k in ["card", "upi", "online", "bank"]):
                tot_card += ret_amt
            elif "credit" in pmode.lower():
                tot_credit += ret_amt
            else:
                tot_cash += ret_amt

            dt_val = ir.get("refundBillDate") or ir.get("paid_date") or ir.get("created_date") or ir.get("investBillDate")
            if isinstance(dt_val, datetime):
                ist_dt = dt_val + timedelta(hours=5, minutes=30)
                dt_str = ist_dt.strftime("%d/%m/%Y %I:%M %p")
            else:
                dt_str = str(dt_val or "")[:19]

            orig_bno = str(ir.get("investBillNo") or "").strip()
            inv_b = invest_bill_map.get(orig_bno, {})

            bt_no = ir.get("billTypeNo") or inv_b.get("billTypeNo") or "INVEST"
            bt_name = billtype_map.get(str(bt_no).strip()) or billtype_map.get(str(ir.get("bill_type") or "").strip()) or bt_no

            # If user filtered by specific bill type (e.g. USG01 or LAB01), apply match
            if bill_type_filter not in ["all", "investigation", "investigation refund", "investigation refunds"]:
                if bill_type_filter not in [bt_no.lower(), bt_name.lower()]:
                    continue

            ir_items = ir.get("item") or ir.get("items") or []
            if not isinstance(ir_items, list):
                ir_items = []

            # Format itemized test details
            item_details = []
            for it in ir_items:
                if isinstance(it, dict):
                    iname = it.get("itemName") or it.get("test_name") or it.get("name") or "Investigation Test"
                    iqty = it.get("quantity") or 1
                    irate = clean_num(it.get("price") or it.get("rate") or it.get("amount") or 0.0)
                    iamt = clean_num(it.get("totalPrice") or it.get("amount") or (irate * clean_num(iqty)))
                    item_details.append({
                        "item_name": iname,
                        "quantity": iqty,
                        "unit_price": irate,
                        "amount": iamt,
                        "billTypeNo": it.get("billTypeNo") or bt_no
                    })

            req_by_id = ir.get("requested_by") or ir.get("created_by") or ""
            appr_by_id = ir.get("approved_by") or ir.get("lastmodified_by") or ir.get("CashierID") or ""

            disp_type = f"Investigation Refund ({bt_name})" if bt_name != "INVEST" else "Investigation Refund"

            records.append({
                "return_bill_no": ir.get("refundBillNo") or str(ir.get("_id")),
                "return_bill_date": dt_str,
                "original_bill_no": orig_bno or "-",
                "bill_type": disp_type,
                "bill_type_code": bt_no,
                "bill_type_label": bt_name,
                "category": "Investigation Refund",
                "uhid": ir.get("uhid") or "-",
                "inpatient_number": ir.get("ipNumber") or ir.get("ip_number") or "-",
                "patient_name": pt_name,
                "return_amount": ret_amt,
                "amount": ret_amt,
                "payment_type": pmode,
                "requested_by": resolve_created_by_name(req_by_id) or "Lab / Staff",
                "requested_by_id": str(req_by_id),
                "approved_by": resolve_created_by_name(appr_by_id) or "Cashier",
                "approved_by_id": str(appr_by_id),
                "pharmacist_id": ir.get("CashierID") or ir.get("created_by") or "",
                "status": ir.get("status") or ir.get("paymentStatus") or "Paid",
                "is_approved": True,
                "outlet_code": ir.get("outlet_code") or "OLET003",
                "items_count": len(ir_items),
                "refund_remarks": ir.get("refundRemarks") or "",
                "medicine_particulars": item_details,
                "billing_details": item_details
            })

        records.sort(key=lambda x: x["return_bill_date"], reverse=True)

        return Response({
            "success": True,
            "report_title": "Sales Return Report",
            "date_range": {"from_date": from_f, "to_date": to_f},
            "summary": {
                "total_returns_count": len(records),
                "total_return_amount": round(tot_amount, 2),
                "pharmacy_return_amount": round(tot_pharmacy, 2),
                "investigation_refund_amount": round(tot_invest, 2),
                "cash_returns": round(tot_cash, 2),
                "card_returns": round(tot_card, 2),
                "credit_returns": round(tot_credit, 2)
            },
            "data": records
        }, status=status.HTTP_200_OK)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass
