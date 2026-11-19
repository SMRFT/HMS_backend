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
    Dedicated Sales Return Report API.
    Audits medicine returns, refunds, customer credits, and restocked items.
    Direct MongoDB query from hospital_salesreturn.
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
            f_str = f_date.strftime("%Y-%m-%d")
            t_str = t_date.strftime("%Y-%m-%d")
            q["$or"] = [
                {"return_bill_date": {"$gte": f_utc, "$lte": t_utc}},
                {"created_date": {"$gte": f_utc, "$lte": t_utc}},
                {"return_date": {"$gte": f_utc, "$lte": t_utc}},
                {"created_date": {"$gte": f_str, "$lte": t_str + " 23:59:59"}},
                {"return_bill_date": {"$gte": f_str, "$lte": t_str + " 23:59:59"}}
            ]
        if outlet_code and outlet_code.lower() != "all":
            q["outlet_code"] = outlet_code

        # Status filter (default includes all valid returns; if explicitly requested)
        status_filter = data.get("status")
        if status_filter and status_filter.lower() == "paid":
            q["$or"] = q.get("$or", []) + [
                {"status": {"$regex": "^paid$", "$options": "i"}},
                {"status": None},
                {"status": {"$exists": False}},
                {"status": ""},
                {"status": "Completed"}
            ]
        elif status_filter and status_filter.lower() == "pending":
            q["status"] = {"$regex": "^pending$", "$options": "i"}
        else:
            # Exclude only cancelled if any
            q["status"] = {"$ne": "Cancelled"}

        returns_list = list(db["hospital_salesreturn"].find(q))
        
        # Patient Name Lookup
        uhids = list(set([str(r.get("uhid")).strip() for r in returns_list if r.get("uhid")]))
        patient_map = {}
        if uhids and db is not None:
            pt_cursor = db["hospital_patient"].find(
                {"uhid": {"$in": uhids}},
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
        tot_cash = 0.0
        tot_card = 0.0
        tot_credit = 0.0

        for r in returns_list:
            ret_amt = clean_num(r.get("return_amount") or r.get("total_amount") or 0.0)
            tot_amount += ret_amt
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
                # Convert UTC to IST
                ist_dt = dt_val + timedelta(hours=5, minutes=30)
                dt_str = ist_dt.strftime("%d/%m/%Y %I:%M %p")
            else:
                dt_str = str(dt_val or "")[:19]

            particulars = r.get("medicine_particulars") or r.get("returned_items") or []
            if not isinstance(particulars, list):
                particulars = []

            records.append({
                "return_bill_no": r.get("return_bill_no") or r.get("return_no") or r.get("sales_return_number") or str(r.get("_id")),
                "return_bill_date": dt_str,
                "original_bill_no": r.get("bill_no") or r.get("Bill_id") or "-",
                "uhid": r.get("uhid") or "-",
                "inpatient_number": r.get("inpatient_number") or "-",
                "patient_name": pt_name,
                "return_amount": ret_amt,
                "amount": ret_amt,
                "payment_type": pmode,
                "pharmacist_id": r.get("pharmacist_id") or r.get("created_by") or "",
                "status": r.get("status") or "Paid",
                "outlet_code": r.get("outlet_code") or "OLET002",
                "items_count": len(particulars),
                "medicine_particulars": particulars
            })

        records.sort(key=lambda x: x["return_bill_date"], reverse=True)

        return Response({
            "success": True,
            "report_title": "Sales Return Report",
            "date_range": {"from_date": from_f, "to_date": to_f},
            "summary": {
                "total_returns_count": len(records),
                "total_return_amount": round(tot_amount, 2),
                "cash_returns": round(tot_cash, 2),
                "card_returns": round(tot_card, 2),
                "credit_returns": round(tot_credit, 2)
            },
            "data": records
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass
