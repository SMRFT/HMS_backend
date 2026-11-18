"""
Cluster 3: Inpatient Advances, Settlements & Dues APIs
======================================================
1. Advance Registration Report
2. Insurance Advance Registration Report
3. IP Advance Collection Register
4. Discharge Patient Bills Summary
5. Discharge Bills Detailed Breakdown
6. Debit & Due Bills Register
7. Discount Bills Register
8. Bill Cancellation Register
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from .core_ledger_engine import AccountsLedgerEngine, clean_num, get_db, parse_date, format_dt, format_ist_time, format_ist_date, format_ist_datetime, to_ist

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def advance_registration_api(request):
    """
    Dedicated Advance Registration Report API.
    Itemized running IP advances with mode breakdown and clean UHID / IP separation.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet"),
            shift_no=data.get("shiftno") or data.get("shift_no")
        )
        
        adv_bills = [b for b in res["bills"] if b["category"] == "ADVANCE"]
        for b in adv_bills:
            adv_val = b.get("gross") or b.get("amount") or (clean_num(b.get("cash")) + clean_num(b.get("bank"))) or 0.0
            b["amount"] = adv_val
            b["advance_amount"] = adv_val
            b["advance"] = adv_val
            b["gross"] = adv_val
            b["mr_no"] = b.get("uhid") or "-"
            b["ip_number"] = b.get("ip_number") or b.get("inpatient_number") or "-"
        
        tot_cash = round(sum(b["cash"] for b in adv_bills), 2)
        tot_card = round(sum(b["bank"] for b in adv_bills), 2)
        tot_adv = round(sum(b.get("advance_amount", 0) for b in adv_bills), 2)
        
        return Response({
            "success": True,
            "report_title": "Advance Registration Report",
            "date_range": res["date_range"],
            "summary": {
                "total_advance": tot_adv,
                "total_advance_amount": tot_adv,
                "cash_advance": tot_cash,
                "total_cash_amount": tot_cash,
                "card_advance": tot_card,
                "total_card_amount": tot_card,
                "total_credit_amount": tot_card
            },
            "total_advance_amount": tot_adv,
            "total_cash_amount": tot_cash,
            "total_credit_amount": tot_card,
            "count": len(adv_bills),
            "data": adv_bills
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def insurance_advance_registration_api(request):
    """
    Dedicated Insurance Advance Registration Report API.
    Corporate and TPA cashless advances, deposits, and claim ledgers matching AdvanceRegistrationInsurence.js.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        f_str = data.get("from_date") or data.get("start_date")
        t_str = data.get("to_date") or data.get("end_date")
        company_filter = data.get("company") or data.get("company_name") or "all"
        outlet_filter = (data.get("outlet_code") or data.get("outlet") or "all").strip()
        
        from datetime import datetime, timedelta
        from .core_ledger_engine import get_db, parse_date, clean_num
        client, db, g_db = get_db()
        try:
            f_d = parse_date(f_str) if f_str else None
            t_d = parse_date(t_str, is_end=True) if t_str else None
            
            # Lookup insurance provider map
            ins_docs = list(db["hospital_insuranceprovider"].find({}, {"company_code": 1, "company_name": 1}))
            ins_code_map = {str(p.get("company_code")): p.get("company_name") for p in ins_docs if p.get("company_code")}
            
            # Query discharge bills in date range with insurance
            q = {"is_cancelled": False}
            if outlet_filter and outlet_filter != "all":
                q["$or"] = [{"outlet_code": outlet_filter}, {"outlet": outlet_filter}, {"SelectedOutlet": outlet_filter}]
            if f_d or t_d:
                df = {}
                if f_d: df["$gte"] = f_d - timedelta(hours=5, minutes=30)
                if t_d: df["$lte"] = t_d - timedelta(hours=5, minutes=30)
                date_filter = [{"bill_date": df}, {"created_date": df}]
                if "$or" in q:
                    q["$and"] = [{"$or": q.pop("$or")}, {"$or": date_filter}]
                else:
                    q["$or"] = date_filter
                
            dis_docs = list(db["hospital_dischargebilling"].find(q).sort("created_date", -1))
            
            # Admissions lookup
            ip_nums = list(set([str(d.get("ip_number")) for d in dis_docs if d.get("ip_number")]))
            uhids = list(set([str(d.get("uhid")) for d in dis_docs if d.get("uhid")]))
            
            adm_docs = list(db["hospital_admission"].find({
                "$or": [{"ipNumber": {"$in": ip_nums}}, {"ip_number": {"$in": ip_nums}}, {"uhid": {"$in": uhids}}]
            }))
            adm_map = {}
            for a in adm_docs:
                if a.get("ipNumber"): adm_map[a["ipNumber"]] = a
                if a.get("ip_number"): adm_map[a["ip_number"]] = a
                if a.get("uhid"): adm_map[a["uhid"]] = a
                
            # Patients lookup
            pat_docs = list(db["hospital_patient"].find({"uhid": {"$in": uhids}}))
            pat_map = {p["uhid"]: f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() for p in pat_docs if p.get("uhid")}
            
            records = []
            for d in dis_docs:
                ip_n = str(d.get("ip_number") or "")
                uhid_n = str(d.get("uhid") or "")
                adm = adm_map.get(ip_n) or adm_map.get(uhid_n) or {}
                
                is_ins = (
                    d.get("is_insurance_bill") is True or
                    str(adm.get("customer_type") or "").upper() == "INSURANCE" or
                    bool(adm.get("insurance_company") or d.get("company_name"))
                )
                if not is_ins:
                    continue
                    
                comp_code = str(adm.get("company_code") or d.get("company_code") or "")
                comp_name = (
                    d.get("company_name") or
                    adm.get("insurance_company") or
                    ins_code_map.get(comp_code) or
                    (f"Company #{comp_code}" if comp_code else "INSURANCE CLAIM")
                )
                
                if company_filter and company_filter.lower() != "all" and comp_name != company_filter:
                    continue
                    
                p_name = pat_map.get(uhid_n) or str(d.get("patient_name") or adm.get("patient_name") or "Patient").strip()
                bill_amt = clean_num(d.get("total_amount"))
                adv_amt = clean_num(d.get("advance_amount"))
                net_paid = clean_num(d.get("net_amount"))
                disallow = clean_num(d.get("disallowed_amount"))
                due_amt = clean_num(d.get("due") or (bill_amt - adv_amt - net_paid))
                
                b_dt = format_ist_date(d.get("bill_date") or d.get("created_date"))
                adm_dt = format_ist_date(adm.get("admissionDateTime") or adm.get("created_date") or b_dt)
                
                records.append({
                    "company_name": comp_name,
                    "company_code": comp_code,
                    "bill_date": b_dt,
                    "ip_number": ip_n,
                    "bill_id": d.get("discharge_id") or d.get("bill_no"),
                    "sh_bill_no": d.get("bill_no") or d.get("bill_number"),
                    "bill_no": d.get("bill_no") or d.get("bill_number"),
                    "uhid": uhid_n,
                    "mr_no": uhid_n,
                    "patient_name": p_name,
                    "admitting_date": adm_dt,
                    "discharge_date": format_ist_date(d.get("discharge_date") or b_dt),
                    "card_number": d.get("id_card_number") or adm.get("card_number") or "-",
                    "service_no": adm.get("service_no") or "-",
                    "claim_reference": d.get("claim_number") or adm.get("claim_reference") or "-",
                    "place": adm.get("place") or "Salem",
                    "bill_amount": bill_amt,
                    "total_amount": bill_amt,
                    "advance": adv_amt,
                    "advance_amount": adv_amt,
                    "despatch_date": str(d.get("despatch_date") or "")[:10],
                    "settlement_date": str(d.get("settlement_date") or "")[:10],
                    "settled_amount": clean_num(d.get("settled_amount") or net_paid),
                    "tds": clean_num(d.get("tds")),
                    "bank": d.get("bank") or "HDFC",
                    "paid_by_patient": net_paid,
                    "disallowed_amount": disallow,
                    "due": max(0.0, due_amt),
                    "settlement_duration": d.get("settlement_duration") or "",
                    "status": d.get("status") or "Billed",
                    "has_insurance": True,
                    "old_billno": ""
                })
                
            tot_bill = round(sum(r["bill_amount"] for r in records), 2)
            tot_adv = round(sum(r["advance"] for r in records), 2)
            tot_settled = round(sum(r["settled_amount"] for r in records), 2)
            tot_due = round(sum(r["due"] for r in records), 2)
            
            return Response({
                "success": True,
                "report_title": "Insurance Advance Registration Report",
                "count": len(records),
                "summary": {
                    "total_bill_amount": tot_bill,
                    "total_advance": tot_adv,
                    "total_settled": tot_settled,
                    "total_due": tot_due,
                    "total_count": len(records)
                },
                "total_advance_amount": tot_adv,
                "data": records
            }, status=status.HTTP_200_OK)
        finally:
            client.close()
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def ip_advance_collection_register_api(request):
    """
    Dedicated IP Advance Collection Register API.
    Running in-patient advances grouped by Floor/Ward matching IPAdvanceReport.js.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        as_on_date_str = data.get("as_on_date") or data.get("date") or data.get("to_date")
        floor_filter = (data.get("floor") or "all").strip()
        advance_filter = (data.get("has_advance") or "all").strip().lower()
        customer_type_filter = (data.get("customer_type") or "all").strip()
        search_query = (data.get("search") or "").strip().lower()
        outlet_filter = (data.get("outlet_code") or data.get("outlet") or "all").strip()
        
        from datetime import datetime, date, timedelta
        from .core_ledger_engine import get_db, parse_date, clean_num
        client, db, g_db = get_db()
        try:
            ref_date = parse_date(as_on_date_str) if as_on_date_str else datetime.now().date()
            if isinstance(ref_date, datetime):
                ref_date = ref_date.date()
                
            # Query currently active admissions
            adm_query = {"is_discharged": False, "is_cancelled": {"$ne": True}}
            if outlet_filter and outlet_filter != "all":
                adm_query["$or"] = [{"outlet_code": outlet_filter}, {"outlet": outlet_filter}, {"SelectedOutlet": outlet_filter}]
            admissions = list(db["hospital_admission"].find(adm_query))
            
            # Insurance map
            ins_docs = list(db["hospital_insuranceprovider"].find({}, {"company_code": 1, "company_name": 1}))
            ins_map = {str(p.get("company_code")): p.get("company_name") for p in ins_docs if p.get("company_code")}

            # Room map
            room_docs = list(db["hospital_room"].find({}, {"room_number": 1, "nursing_station": 1, "floor": 1, "room_category": 1}))
            room_map = {str(r.get("room_number")): r for r in room_docs if r.get("room_number")}
            
            # Patient map
            uhids = list(set([str(a.get("uhid")).strip() for a in admissions if a.get("uhid")]))
            patient_docs = list(db["hospital_patient"].find({"uhid": {"$in": uhids}}))
            patient_map = {}
            for p in patient_docs:
                full_name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
                if p.get("uhid"):
                    patient_map[p["uhid"].strip().upper()] = full_name
                    
            def resolve_floor(room_no, room_obj):
                if not room_no or room_no == "N/A": return "ALL FLOOR"
                r_str = str(room_no).strip().upper()
                nursing = str((room_obj.get("nursing_station") or "") if room_obj else "").upper()
                flr = str((room_obj.get("floor") or "") if room_obj else "").upper()
                if "FIRST" in nursing or "FIRST" in flr: return "1ST FLOOR"
                if "SECOND" in nursing or "SECOND" in flr: return "2ND FLOOR"
                if "THIRD" in nursing or "THIRD" in flr: return "3RD FLOOR"
                if "MICU" in nursing or "MICU" in r_str: return "MICU"
                if "SICU" in nursing or "SICU" in r_str: return "SICU"
                if "NICU" in nursing or "NICU" in r_str: return "NICU"
                if "CHEMO" in nursing or "CHEMO" in r_str: return "CHEMO"
                if "DAYCAR" in nursing or "DAYCAR" in r_str: return "DAYCAR"
                num_part = "".join(c for c in r_str if c.isdigit())
                if num_part:
                    num = int(num_part)
                    if 100 <= num <= 399: return "1ST FLOOR"
                    if 400 <= num <= 499: return "2ND FLOOR"
                    if 500 <= num <= 599: return "3RD FLOOR"
                if nursing: return nursing
                if flr: return flr
                return "1ST FLOOR"
                
            raw_records = []
            distinct_floors = set()
            
            for adm in admissions:
                ip_num = str(adm.get("ipNumber") or "").strip()
                uhid_val = str(adm.get("uhid") or "").strip()
                p_name = patient_map.get(uhid_val.upper()) or str(adm.get("patient_name") or "Patient").strip()
                
                # Active room
                room_no = "N/A"
                room_details = adm.get("room_details") or []
                active_r = None
                if isinstance(room_details, list) and room_details:
                    for r in reversed(room_details):
                        if isinstance(r, dict) and r.get("is_roomActive") in (True, "True", "true", 1, "1"):
                            active_r = r
                            break
                    if not active_r and room_details:
                        active_r = room_details[-1]
                if active_r and isinstance(active_r, dict):
                    room_no = str(active_r.get("roomNo") or "N/A").strip()
                    
                room_obj = room_map.get(room_no)
                floor_name = resolve_floor(room_no, room_obj)
                distinct_floors.add(floor_name)
                
                # Resolve admitting date & no_of_days
                adm_dt = adm.get("admissionDateTime") or adm.get("created_date")
                adm_date = None
                if isinstance(adm_dt, str):
                    try:
                        adm_date = datetime.fromisoformat(adm_dt.replace('Z', '+00:00')).date()
                    except Exception:
                        adm_date = parse_date(adm_dt)
                elif isinstance(adm_dt, datetime):
                    adm_date = adm_dt.date()
                elif isinstance(adm_dt, date):
                    adm_date = adm_dt

                if not adm_date:
                    adm_date = ref_date

                no_of_days = max(0, (ref_date - adm_date).days)

                # Advance payments on admission
                adv_payments = adm.get("advance_payments") or []
                total_adv = 0.0
                advance_items = []
                if isinstance(adv_payments, list):
                    for p in adv_payments:
                        if isinstance(p, dict):
                            is_active = p.get("is_advanceActive", True)
                            p_status = p.get("status", "Paid")
                            if is_active and p_status != "Cancelled" and not p.get("is_refund"):
                                amt = clean_num(p.get("advance_amount") or p.get("amount") or 0)
                                total_adv += amt
                                advance_items.append({
                                    "bill_no": p.get("bill_no") or "",
                                    "advance_id": p.get("advance_id") or "",
                                    "date": format_ist_date(p.get("date") or p.get("bill_date")),
                                    "amount": round(amt, 2),
                                    "ip_advance": round(clean_num(p.get("ip_advance", 0)), 2),
                                    "billing_advance": round(clean_num(p.get("billing_advance", 0)), 2),
                                    "payment_mode": (p.get("payment_details", {}).get("method") if isinstance(p.get("payment_details"), dict) else p.get("payment_mode")) or "Cash",
                                    "status": p_status
                                })

                total_adv = round(total_adv, 2)
                
                # Resolve Company / Insurance Name
                comp_name = (
                    adm.get("insurance_company") or
                    ins_map.get(str(adm.get("company_code") or "")) or
                    adm.get("packageName") or
                    (adm.get("customer_type") if adm.get("customer_type") and adm.get("customer_type") != "General" else "") or
                    ""
                ).strip()

                c_type = str(adm.get("customer_type") or "General").capitalize()
                
                record = {
                    "sl_no": 0,
                    "room": room_no,
                    "room_no": room_no,
                    "ip_number": ip_num,
                    "uhid": uhid_val,
                    "mr_no": uhid_val,
                    "patient_name": p_name,
                    "admitting_date": adm_date.strftime("%d/%m/%Y"),
                    "admitting_date_iso": adm_date.isoformat(),
                    "admission_date": adm_date.strftime("%d/%m/%Y"),
                    "no_of_days": no_of_days,
                    "advance": total_adv,
                    "advance_amount": total_adv,
                    "amount": total_adv,
                    "company_name": comp_name,
                    "customer_type": c_type,
                    "floor": floor_name,
                    "doctor_name": str(adm.get("consultingDoctor") or adm.get("admittingDoctor") or "Dr. Duty").strip(),
                    "admitting_doctor": str(adm.get("admittingDoctor") or adm.get("consultingDoctor") or "").strip(),
                    "has_advance": total_adv > 0,
                    "advance_items": advance_items,
                    "advance_details": advance_items
                }
                
                # Filters
                if floor_filter != "all" and floor_name.lower() != floor_filter.lower(): continue
                if advance_filter == "with_advance" and total_adv <= 0: continue
                if advance_filter == "zero_advance" and total_adv > 0: continue
                if customer_type_filter != "all":
                    c_val = c_type.lower()
                    c_comp = comp_name.lower()
                    req_c = customer_type_filter.lower()
                    if req_c == "general" and (comp_name or c_val not in ("general", "")):
                        continue
                    elif req_c == "insurance" and not (comp_name or "insurance" in c_val):
                        continue
                    elif req_c not in ("general", "insurance") and req_c not in c_val and req_c not in c_comp:
                        continue
                if search_query:
                    match = (
                        search_query in ip_num.lower() or
                        search_query in uhid_val.lower() or
                        search_query in p_name.lower() or
                        search_query in room_no.lower() or
                        search_query in comp_name.lower() or
                        search_query in floor_name.lower()
                    )
                    if not match: continue
                    
                raw_records.append(record)
                
            # Floor Ordering Definition
            floor_order = [
                "1ST FLOOR", "2ND FLOOR", "3RD FLOOR", "ALL FLOOR",
                "MICU", "SICU", "NICU", "CHEMO", "DAYCAR", "GW-A", "RECOVERY WARD"
            ]
            def get_floor_sort_key(flr):
                flr_u = flr.upper()
                try:
                    return (0, floor_order.index(flr_u), flr_u)
                except ValueError:
                    return (1, 999, flr_u)

            # Sort records
            raw_records.sort(key=lambda x: (
                get_floor_sort_key(x["floor"]),
                x["room"],
                x["admitting_date_iso"]
            ))

            for idx, r in enumerate(raw_records, 1):
                r["sl_no"] = idx

            # Floor grouping
            grouped_dict = {}
            for r in raw_records:
                flr = r["floor"]
                if flr not in grouped_dict:
                    grouped_dict[flr] = []
                grouped_dict[flr].append(r)
                
            grouped_data = []
            for flr in sorted(grouped_dict.keys(), key=get_floor_sort_key):
                flr_records = grouped_dict[flr]
                subtotal_adv = round(sum(clean_num(item["advance"]) for item in flr_records), 2)
                grouped_data.append({
                    "floor": flr,
                    "records": flr_records,
                    "patients": flr_records,
                    "count": len(flr_records),
                    "subtotal_advance": subtotal_adv,
                    "subtotal": subtotal_adv
                })

            distinct_floors = sorted(list({r["floor"] for r in raw_records}), key=get_floor_sort_key)
            tot_patients = len(raw_records)
            with_adv = sum(1 for r in raw_records if r["has_advance"])
            zero_adv = tot_patients - with_adv
            tot_adv_sum = round(sum(clean_num(r["advance"]) for r in raw_records), 2)
            
            return Response({
                "success": True,
                "report_title": "IP Advance Collection Register",
                "data": raw_records,
                "grouped_data": grouped_data,
                "floors_list": distinct_floors,
                "summary": {
                    "total_patients": tot_patients,
                    "total_with_advance": with_adv,
                    "total_zero_advance": zero_adv,
                    "total_advance": tot_adv_sum,
                    "as_on_date": ref_date.strftime("%d/%m/%Y"),
                    "as_on_date_iso": ref_date.isoformat()
                }
            }, status=status.HTTP_200_OK)
        finally:
            client.close()
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def discharge_bills_summary_api(request):
    """
    Dedicated Discharge Patient Bills Summary API.
    IP final clearance and settlements.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet")
        )
        dis_bills = [b for b in res["bills"] if b["category"] == "DISCHARGE"]
        for b in dis_bills:
            g_amt = clean_num(b.get("gross_amount") or b.get("gross") or b.get("bill_amount") or b.get("total_amount") or 0.0)
            adv_adj = clean_num(b.get("advance_adjustment") or b.get("advance_adjusted") or b.get("advance_amount") or 0.0)
            c_val = clean_num(b.get("cash"))
            k_val = clean_num(b.get("credit") or b.get("bank") or b.get("card"))
            net_amt = clean_num(b.get("net_paid") or b.get("net_settlement") or (c_val + k_val) or b.get("amount") or 0.0)
            if c_val == 0.0 and k_val == 0.0:
                pm = str(b.get("payment_mode") or "").lower()
                if "cash" in pm or not pm:
                    c_val = net_amt
                else:
                    k_val = net_amt
            b["bill_amount"] = g_amt
            b["gross_amount"] = g_amt
            b["gross_bill"] = g_amt
            b["gross"] = g_amt
            b["advance_adjusted"] = adv_adj
            b["advance_adjustment"] = adv_adj
            b["net_settlement"] = net_amt
            b["net_paid"] = net_amt
            b["cash_amount"] = round(c_val, 2)
            b["cash"] = round(c_val, 2)
            b["credit_amount"] = round(k_val, 2)
            b["credit"] = round(k_val, 2)
            b["mr_no"] = b.get("uhid") or "-"

        tot_gross = round(sum(b["bill_amount"] for b in dis_bills), 2)
        tot_adv = round(sum(b["advance_adjusted"] for b in dis_bills), 2)
        tot_net = round(sum(b["net_settlement"] for b in dis_bills), 2)
        tot_cash = round(sum(b["cash"] for b in dis_bills), 2)
        tot_credit = round(sum(b["credit"] for b in dis_bills), 2)

        return Response({
            "success": True,
            "report_title": "Discharge Patient Bills Summary",
            "date_range": res["date_range"],
            "count": len(dis_bills),
            "summary": {
                "total_gross_bill": tot_gross,
                "total_advance_adjusted": tot_adv,
                "total_net_settlement": tot_net,
                "total_settlement": tot_net,
                "total_cash": tot_cash,
                "total_credit": tot_credit,
                "cash_amount": tot_cash,
                "credit_amount": tot_credit
            },
            "total_amount": tot_gross,
            "total_cash": tot_cash,
            "total_card": round(sum(b["bank"] for b in dis_bills), 2),
            "total_credit": tot_credit,
            "data": dis_bills
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def discharge_bills_detailed_api(request):
    """
    Dedicated Discharge Bills Detailed Breakdown API.
    Line-item billing audit on final discharge.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date")
        )
        dis_bills = [b for b in res["bills"] if b["category"] == "DISCHARGE"]
        for b in dis_bills:
            b["room_charge"] = b.get("room_charges") or 0.0
            b["nursing_charge"] = b.get("nursing_charges") or 0.0
            b["doctor_charge"] = b.get("doctor_charges") or 0.0
            b["investigation_charge"] = b.get("lab_charges") or 0.0
            b["pharmacy_charge"] = b.get("pharmacy_charges") or 0.0
            b["total_amount"] = b.get("gross_amount") or b.get("gross") or (b["room_charge"] + b["nursing_charge"] + b["doctor_charge"] + b["investigation_charge"] + b["pharmacy_charge"])
            b["mr_no"] = b.get("uhid") or "-"

        tot_room = round(sum(b["room_charge"] for b in dis_bills), 2)
        tot_nurs = round(sum(b["nursing_charge"] for b in dis_bills), 2)
        tot_doc = round(sum(b["doctor_charge"] for b in dis_bills), 2)
        tot_lab = round(sum(b["investigation_charge"] for b in dis_bills), 2)
        tot_pharm = round(sum(b["pharmacy_charge"] for b in dis_bills), 2)
        tot_inv = round(sum(b["total_amount"] for b in dis_bills), 2)

        return Response({
            "success": True,
            "report_title": "Discharge Bills Detailed Breakdown",
            "date_range": res["date_range"],
            "count": len(dis_bills),
            "summary": {
                "total_room": tot_room,
                "total_nursing": tot_nurs,
                "total_doctor": tot_doc,
                "total_investigation": tot_lab,
                "total_pharmacy": tot_pharm,
                "total_invoiced": tot_inv
            },
            "data": dis_bills
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def debit_and_due_bills_api(request):
    """
    Dedicated Debit & Due Bills Register API.
    Pending receivables and credit balances.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        client, db, g_db = get_db()
        try:
            # Query bills with pending status or debit amounts
            pending_docs = list(db["hospital_billing"].find({
                "payment_status": {"$in": ["Pending", "Cash Pending", "Partial"]}
            }, {"bill_number": 1, "uhid": 1, "patient_name": 1, "total_fees": 1, "billed_date": 1}))
            
            rows = []
            for p in pending_docs:
                amt = clean_num(p.get("total_fees"))
                rows.append({
                    "bill_no": p.get("bill_number"),
                    "uhid": p.get("uhid"),
                    "mr_no": p.get("uhid") or "-",
                    "patient_name": p.get("patient_name") or "Patient",
                    "amount": amt,
                    "date": format_ist_date(p.get("billed_date"))
                })
                
            return Response({
                "success": True,
                "report_title": "Debit & Due Bills Register",
                "count": len(rows),
                "total_due_amount": round(sum(r["amount"] for r in rows), 2),
                "summary": {"total_due_amount": round(sum(r["amount"] for r in rows), 2)},
                "data": rows
            }, status=status.HTTP_200_OK)
        finally:
            client.close()
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def discount_bills_api(request):
    """
    Dedicated Discount Bills Register API.
    Management waivers, concessions, and authorized discounts across all billing modules.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        f_str = data.get("from_date") or data.get("start_date")
        t_str = data.get("to_date") or data.get("end_date")
        f_d = parse_date(f_str) if f_str else None
        t_d = parse_date(t_str, is_end=True) if t_str else None

        client, db, g_db = get_db()
        try:
            rows = []
            
            # 1. Search hospital_dischargebilling
            d_docs = list(db["hospital_dischargebilling"].find())
            for d in d_docs:
                disc = clean_num(d.get("discount_amount"))
                if disc > 0:
                    raw_dt = d.get("created_date") or d.get("discharge_date")
                    d_dt = parse_date(raw_dt)
                    if f_d and d_dt and d_dt < f_d: continue
                    if t_d and d_dt and d_dt > t_d: continue
                    dt_str = format_ist_date(raw_dt)
                    tot = clean_num(d.get("total_amount"))
                    rows.append({
                        "bill_no": d.get("bill_no") or d.get("bill_number"),
                        "uhid": d.get("uhid") or "",
                        "mr_no": d.get("uhid") or "-",
                        "category": "DISCHARGE",
                        "patient_name": str(d.get("patient_name") or d.get("patientname") or "").strip(),
                        "authorized_by": d.get("authorized_by") or d.get("doctor_name") or "Management",
                        "reason": d.get("disc_reason") or "Management Concession",
                        "bill_amount": tot if tot > 0 else disc,
                        "discount_amount": disc,
                        "net_amount": round((tot if tot > 0 else disc) - disc, 2),
                        "date": dt_str
                    })
                    
            # 2. Search hospital_billing
            b_docs = list(db["hospital_billing"].find({
                "$or": [{"discount_amount": {"$exists": True, "$ne": 0}}, {"discount": {"$exists": True, "$ne": 0}}]
            }))
            for b in b_docs:
                disc = clean_num(b.get("discount_amount") or b.get("discount"))
                if disc > 0:
                    raw_dt = b.get("billed_date") or b.get("created_date")
                    b_dt = parse_date(raw_dt)
                    if f_d and b_dt and b_dt < f_d: continue
                    if t_d and b_dt and b_dt > t_d: continue
                    dt_str = format_ist_date(raw_dt)
                    tot = clean_num(b.get("total_fees") or b.get("total_amount"))
                    rows.append({
                        "bill_no": b.get("bill_number") or b.get("bill_no"),
                        "uhid": b.get("uhid") or "",
                        "mr_no": b.get("uhid") or "-",
                        "category": "REGISTRATION",
                        "patient_name": str(b.get("patient_name") or "").strip(),
                        "authorized_by": b.get("doctor_name") or "Management",
                        "reason": "Authorized Concession",
                        "bill_amount": tot if tot > 0 else disc,
                        "discount_amount": disc,
                        "net_amount": round((tot if tot > 0 else disc) - disc, 2),
                        "date": dt_str
                    })
                    
            # 3. Patient Name Backfill
            missing_uhids = list(set([r["uhid"] for r in rows if r["uhid"] and not r["patient_name"]]))
            if missing_uhids:
                p_docs = list(db["hospital_patient"].find({"uhid": {"$in": missing_uhids}}, {"uhid": 1, "firstName": 1, "lastName": 1}))
                p_map = {p["uhid"]: f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() for p in p_docs}
                reg_docs = list(db["hospital_patientregistration"].find(
                    {"$or": [{"uhid": {"$in": missing_uhids}}, {"PatientId": {"$in": missing_uhids}}]},
                    {"PatientId": 1, "uhid": 1, "firstName": 1, "lastName": 1}
                ))
                for pr in reg_docs:
                    nm = f"{pr.get('firstName', '')} {pr.get('lastName', '')}".strip()
                    if pr.get("uhid"): p_map[pr["uhid"]] = nm
                    if pr.get("PatientId"): p_map[pr["PatientId"]] = nm
                    
                for r in rows:
                    if not r["patient_name"] and r["uhid"] in p_map:
                        r["patient_name"] = p_map[r["uhid"]]
                    if not r["patient_name"]:
                        r["patient_name"] = "Patient"
                        
            tot_disc = round(sum(r["discount_amount"] for r in rows), 2)
            tot_gross = round(sum(r["bill_amount"] for r in rows), 2)
            tot_net = round(sum(r["net_amount"] for r in rows), 2)
            
            return Response({
                "success": True,
                "report_title": "Discount Bills Register",
                "count": len(rows),
                "summary": {
                    "total_discount_amount": tot_disc,
                    "total_bill_amount": tot_gross,
                    "total_net_amount": tot_net
                },
                "total_discount_amount": tot_disc,
                "data": rows
            }, status=status.HTTP_200_OK)
        finally:
            client.close()
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def bill_cancellation_register_api(request):
    """
    Dedicated Bill Cancellation Register API.
    Audit log of cancelled invoices, refunded receipts, and void vouchers.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        client, db, g_db = get_db()
        try:
            cancels = list(db["hospital_billing"].find({
                "$or": [{"status": "Cancelled"}, {"is_cancelled": True}]
            }, {"bill_number": 1, "uhid": 1, "patient_name": 1, "total_fees": 1, "cancellation_reason": 1, "cancelled_date": 1, "cancelled_by": 1}))
            
            rows = []
            for c in cancels:
                rows.append({
                    "bill_no": c.get("bill_number"),
                    "uhid": c.get("uhid"),
                    "patient_name": c.get("patient_name") or "Patient",
                    "amount": clean_num(c.get("total_fees")),
                    "reason": c.get("cancellation_reason") or "Cancelled by operator",
                    "cancelled_by": c.get("cancelled_by") or "STAFF",
                    "date": format_ist_date(c.get("cancelled_date"))
                })
                
            return Response({
                "success": True,
                "report_title": "Bill Cancellation Register",
                "count": len(rows),
                "total_cancelled_amount": round(sum(r["amount"] for r in rows), 2),
                "data": rows
            }, status=status.HTTP_200_OK)
        finally:
            client.close()
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
