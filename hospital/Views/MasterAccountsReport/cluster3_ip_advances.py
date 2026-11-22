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
from datetime import datetime, date, timedelta
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
        company_filter = (data.get("company") or data.get("company_name") or data.get("category") or data.get("billType") or "all").strip()
        outlet_filter = (data.get("outlet_code") or data.get("outlet") or "all").strip()
        
        from datetime import datetime, timedelta
        from .core_ledger_engine import get_db, parse_date, clean_num, format_ist_date
        client, db, g_db = get_db()
        try:
            f_d = parse_date(f_str) if f_str else None
            t_d = parse_date(t_str, is_end=True) if t_str else None
            
            # Lookup insurance provider map
            ins_docs = list(db["hospital_insuranceprovider"].find({}, {"company_code": 1, "company_name": 1}))
            ins_code_map = {}
            ins_name_to_code = {}
            for p in ins_docs:
                c_code = str(p.get("company_code") or "").strip()
                c_name = str(p.get("company_name") or "").strip()
                if c_code:
                    ins_code_map[c_code] = c_name
                if c_name:
                    ins_name_to_code[c_name.lower()] = c_code
            
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
                    
                comp_code = str(adm.get("company_code") or d.get("company_code") or adm.get("companyCode") or "").strip()
                adm_ins = str(adm.get("insurance_company") or adm.get("insuranceCompanyName") or "").strip()
                dis_ins = str(d.get("company_name") or d.get("insurance_company") or "").strip()
                
                comp_name = None
                if dis_ins and not dis_ins.isdigit() and dis_ins not in ins_code_map:
                    comp_name = dis_ins
                elif adm_ins and not adm_ins.isdigit() and adm_ins not in ins_code_map:
                    comp_name = adm_ins
                elif comp_code and ins_code_map.get(comp_code):
                    comp_name = ins_code_map[comp_code]
                elif dis_ins and ins_code_map.get(dis_ins):
                    comp_name = ins_code_map[dis_ins]
                elif adm_ins and ins_code_map.get(adm_ins):
                    comp_name = ins_code_map[adm_ins]
                elif dis_ins:
                    comp_name = dis_ins
                elif adm_ins:
                    comp_name = adm_ins
                elif comp_code:
                    comp_name = f"Company #{comp_code}"
                else:
                    comp_name = "INSURANCE CLAIM"

                if not comp_code and comp_name:
                    comp_code = ins_name_to_code.get(comp_name.lower(), "")
                
                if company_filter and company_filter.lower() != "all":
                    c_filt_lower = company_filter.lower().strip()
                    if comp_name.lower() != c_filt_lower and comp_code.lower() != c_filt_lower and c_filt_lower not in comp_name.lower():
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
                    "card_number": d.get("id_card_number") or adm.get("card_number") or adm.get("policy_no") or "-",
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

            # Group records by Company Name (case-insensitive grouping)
            company_groups_map = {}
            for r in records:
                c_name = str(r["company_name"]).strip()
                c_key = c_name.upper()
                if c_key not in company_groups_map:
                    company_groups_map[c_key] = {
                        "company_name": c_name,
                        "company_code": r.get("company_code") or "",
                        "count": 0,
                        "total_bill_amount": 0.0,
                        "total_advance": 0.0,
                        "total_settled": 0.0,
                        "total_patient_paid": 0.0,
                        "total_disallowed": 0.0,
                        "total_due": 0.0,
                        "items": []
                    }
                grp = company_groups_map[c_key]
                grp["count"] += 1
                grp["total_bill_amount"] = round(grp["total_bill_amount"] + r["bill_amount"], 2)
                grp["total_advance"] = round(grp["total_advance"] + r["advance"], 2)
                grp["total_settled"] = round(grp["total_settled"] + r["settled_amount"], 2)
                grp["total_patient_paid"] = round(grp["total_patient_paid"] + r["paid_by_patient"], 2)
                grp["total_disallowed"] = round(grp["total_disallowed"] + r["disallowed_amount"], 2)
                grp["total_due"] = round(grp["total_due"] + r["due"], 2)
                grp["items"].append(r)
                if r.get("company_code") and not grp["company_code"]:
                    grp["company_code"] = r["company_code"]

            grouped_data = sorted(list(company_groups_map.values()), key=lambda g: g["company_name"].upper())

            # Unique companies list for dropdown
            unique_companies = [
                {"name": g["company_name"], "code": g["company_code"], "count": g["count"]}
                for g in grouped_data
            ]
                
            tot_bill = round(sum(r["bill_amount"] for r in records), 2)
            tot_adv = round(sum(r["advance"] for r in records), 2)
            tot_settled = round(sum(r["settled_amount"] for r in records), 2)
            tot_patient_paid = round(sum(r["paid_by_patient"] for r in records), 2)
            tot_disallowed = round(sum(r["disallowed_amount"] for r in records), 2)
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
                    "total_patient_paid": tot_patient_paid,
                    "total_disallowed": tot_disallowed,
                    "total_count": len(records),
                    "total_companies": len(grouped_data)
                },
                "total_advance_amount": tot_adv,
                "unique_companies": unique_companies,
                "grouped_data": grouped_data,
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
    Running in-patient advances with company-wise and floor-wise filtering and grouping.
    """
    try:
        data = request.data if request.method == "POST" else (
            request.query_params if hasattr(request, "query_params") else getattr(request, "GET", {})
        )
        as_on_date_str = data.get("as_on_date") or data.get("date") or data.get("to_date")
        floor_filter = (data.get("floor") or "all").strip()
        company_filter = (data.get("company") or data.get("company_name") or "all").strip()
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
                
            # 1. Fetch all discharged IP numbers from hospital_dischargebilling
            discharged_docs = list(db["hospital_dischargebilling"].find(
                {"is_cancelled": False},
                {"ip_number": 1, "ipNumber": 1, "inpatient_number": 1, "bill_date": 1, "created_date": 1}
            ))
            discharged_ips = set()
            for d in discharged_docs:
                d_dt = d.get("bill_date") or d.get("created_date")
                d_d = parse_date(d_dt)
                if isinstance(d_d, datetime):
                    d_d = d_d.date()
                if not ref_date or not d_d or d_d <= ref_date:
                    for k in ["ip_number", "ipNumber", "inpatient_number"]:
                        val = str(d.get(k) or "").strip()
                        if val:
                            discharged_ips.add(val)

            # 2. Query admissions and filter out discharged, cancelled & future patients
            adm_query = {"is_discharged": False}
            if outlet_filter and outlet_filter != "all":
                adm_query["$or"] = [{"outlet_code": outlet_filter}, {"outlet": outlet_filter}, {"SelectedOutlet": outlet_filter}]
            raw_admissions = list(db["hospital_admission"].find(adm_query))
            
            admissions = []
            for adm in raw_admissions:
                ip_num = str(adm.get("ipNumber") or "").strip()
                if not ip_num or ip_num in discharged_ips:
                    continue
                if adm.get("is_discharged") in (True, "True", "true", 1, "1"):
                    continue
                if adm.get("is_admitted") in (False, "False", "false", 0, "0"):
                    continue
                if adm.get("is_cancelled") in (True, "True", "true", 1, "1"):
                    continue
                w_status = str(adm.get("ward_status") or "").strip().lower()
                if any(k in w_status for k in ["discharg", "billed", "clearance", "settled", "completed"]):
                    continue
                
                # Check admission date
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

                if adm_date and ref_date and adm_date > ref_date:
                    continue

                admissions.append(adm)
            
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
                if "DIALYSIS" in nursing or "DLS" in r_str: return "DIALYSIS"
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
            all_available_floors = set()
            all_available_companies = set()
            
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
                all_available_floors.add(floor_name)
                
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
                                p_dt_raw = p.get("date") or p.get("bill_date") or p.get("created_date")
                                p_d = parse_date(p_dt_raw)
                                if isinstance(p_d, datetime):
                                    p_d = p_d.date()
                                if p_d and ref_date and p_d > ref_date:
                                    continue
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
                if not comp_name or comp_name.upper() in ("GENERAL", "CASH"):
                    comp_name = "GENERAL"

                all_available_companies.add(comp_name)
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
                if floor_filter != "all" and floor_name.lower() != floor_filter.lower():
                    continue

                if company_filter != "all":
                    c_filt = company_filter.lower().strip()
                    comp_lower = comp_name.lower()
                    if c_filt != comp_lower and c_filt not in comp_lower:
                        continue

                if advance_filter == "with_advance" and total_adv <= 0:
                    continue
                if advance_filter == "zero_advance" and total_adv > 0:
                    continue

                if customer_type_filter != "all":
                    c_val = c_type.lower()
                    c_comp = comp_name.lower()
                    req_c = customer_type_filter.lower()
                    if req_c == "general" and (comp_name != "GENERAL" and c_val not in ("general", "")):
                        continue
                    elif req_c == "insurance" and (comp_name == "GENERAL" or "insurance" not in c_val):
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
                    if not match:
                        continue
                    
                raw_records.append(record)
                
            # Floor Ordering Definition
            floor_order = [
                "1ST FLOOR", "2ND FLOOR", "3RD FLOOR", "ALL FLOOR",
                "MICU", "SICU", "NICU", "CHEMO", "DAYCAR", "DIALYSIS", "GW-A", "RECOVERY WARD"
            ]
            def get_floor_sort_key(flr):
                flr_u = str(flr).upper()
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

            # 1. Floor grouping
            floor_grouped_dict = {}
            for r in raw_records:
                flr = r["floor"]
                if flr not in floor_grouped_dict:
                    floor_grouped_dict[flr] = []
                floor_grouped_dict[flr].append(r)
                
            grouped_data = []
            for flr in sorted(floor_grouped_dict.keys(), key=get_floor_sort_key):
                flr_records = floor_grouped_dict[flr]
                subtotal_adv = round(sum(clean_num(item["advance"]) for item in flr_records), 2)
                grouped_data.append({
                    "floor": flr,
                    "records": flr_records,
                    "patients": flr_records,
                    "count": len(flr_records),
                    "subtotal_advance": subtotal_adv,
                    "subtotal": subtotal_adv
                })

            # 2. Company grouping
            comp_grouped_dict = {}
            for r in raw_records:
                c = r["company_name"]
                if c not in comp_grouped_dict:
                    comp_grouped_dict[c] = []
                comp_grouped_dict[c].append(r)

            company_grouped_data = []
            for c in sorted(comp_grouped_dict.keys()):
                c_records = comp_grouped_dict[c]
                subtotal_adv = round(sum(clean_num(item["advance"]) for item in c_records), 2)
                company_grouped_data.append({
                    "company_name": c,
                    "company": c,
                    "records": c_records,
                    "patients": c_records,
                    "count": len(c_records),
                    "subtotal_advance": subtotal_adv,
                    "subtotal": subtotal_adv
                })

            distinct_floors = sorted(list(all_available_floors), key=get_floor_sort_key)
            distinct_companies = sorted(list(all_available_companies))

            tot_patients = len(raw_records)
            with_adv = sum(1 for r in raw_records if r["has_advance"])
            zero_adv = tot_patients - with_adv
            tot_adv_sum = round(sum(clean_num(r["advance"]) for r in raw_records), 2)
            
            return Response({
                "success": True,
                "report_title": "IP Advance Collection Register",
                "data": raw_records,
                "records": raw_records,
                "grouped_data": grouped_data,
                "floor_grouped_data": grouped_data,
                "company_grouped_data": company_grouped_data,
                "floors_list": distinct_floors,
                "companies_list": distinct_companies,
                "unique_companies": distinct_companies,
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
        mode_param = (data.get("payment_mode") or data.get("mode") or data.get("bill_type") or data.get("category") or "").strip()

        res = AccountsLedgerEngine.get_ledger_data(
            from_str=data.get("from_date") or data.get("start_date"),
            to_str=data.get("to_date") or data.get("end_date"),
            outlet_code=data.get("outlet_code") or data.get("outlet")
        )
        all_dis_bills = [b for b in res["bills"] if b["category"] == "DISCHARGE"]
        for b in all_dis_bills:
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

        # Filter by payment mode if specified
        if mode_param and mode_param.lower() not in ["all", "all payment modes", "all types"]:
            fm = mode_param.strip().lower()
            dis_bills = []
            for b in all_dis_bills:
                bm = str(b.get("payment_mode") or "").strip().lower()
                if fm == "cash":
                    if bm == "cash":
                        dis_bills.append(b)
                elif fm in ["card", "credit card", "bank", "online", "pos"]:
                    if any(k in bm for k in ["card", "bank", "online", "pos", "upi", "neft"]):
                        dis_bills.append(b)
                elif "multi" in fm:
                    if "multi" in bm:
                        dis_bills.append(b)
                elif fm == "cheque":
                    if "cheque" in bm:
                        dis_bills.append(b)
                elif fm in bm:
                    dis_bills.append(b)
        else:
            dis_bills = all_dis_bills

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
            "total_card": round(sum(b.get("bank", 0) for b in dis_bills), 2),
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
    Audit log of cancelled invoices, refunded receipts, and void vouchers across
    Pharmacy, Investigations, IP Billing, Consultation Refunds, and Advance Refunds.
    """
    client = None
    try:
        data = request.data if request.method == "POST" else request.query_params
        from_f = data.get("from_date") or data.get("start_date")
        to_f = data.get("to_date") or data.get("end_date")

        f_date = parse_date(from_f) if from_f else None
        t_date = parse_date(to_f, is_end=True) if to_f else None

        client, db, g_db = get_db()

        def make_date_clauses(date_fields):
            if not f_date and not t_date:
                return []
            clauses = []
            if f_date and t_date:
                f_utc = f_date - timedelta(hours=5, minutes=30)
                t_utc = t_date - timedelta(hours=5, minutes=30)
                f_str = f_date.strftime("%Y-%m-%d")
                t_str = t_date.strftime("%Y-%m-%d")
                for f in date_fields:
                    clauses.append({f: {"$gte": f_utc, "$lte": t_utc}})
                    clauses.append({f: {"$gte": f_str, "$lte": t_str + " 23:59:59"}})
            elif f_date:
                f_utc = f_date - timedelta(hours=5, minutes=30)
                f_str = f_date.strftime("%Y-%m-%d")
                for f in date_fields:
                    clauses.append({f: {"$gte": f_utc}})
                    clauses.append({f: {"$gte": f_str}})
            elif t_date:
                t_utc = t_date - timedelta(hours=5, minutes=30)
                t_str = t_date.strftime("%Y-%m-%d")
                for f in date_fields:
                    clauses.append({f: {"$lte": t_utc}})
                    clauses.append({f: {"$lte": t_str + " 23:59:59"}})
            return clauses

        rows = []
        uhid_set = set()

        # 1. Pharmacy Cancelled Bills & Estimates
        ph_date_clauses = make_date_clauses(["cancelled_date", "bill_date", "created_date"])
        q_ph = {
            "$or": [{"billing_status": "Cancelled"}, {"status": "Cancelled"}, {"is_cancelled": True}]
        }
        if ph_date_clauses:
            q_ph = {"$and": [q_ph, {"$or": ph_date_clauses}]}

        for p in db["hospital_pharmacybilling"].find(q_ph):
            amt = clean_num(p.get("total_amount") or p.get("net_amount"))
            dt = p.get("cancelled_date") or p.get("bill_date") or p.get("created_date")
            bno = p.get("bill_no") or p.get("estimate_no") or str(p.get("Bill_id") or "")
            u = str(p.get("uhid") or "").strip()
            if u:
                uhid_set.add(u)
            rows.append({
                "bill_no": bno,
                "date": format_ist_date(dt),
                "date_raw": dt,
                "category": "Pharmacy",
                "mr_no": u or "-",
                "patient_name": p.get("patientname") or p.get("patient_name") or "",
                "amount": amt,
                "cancelled_by": p.get("cancelled_by") or p.get("deleted_by") or p.get("created_by") or "Staff",
                "reason": p.get("cancel_reason") or p.get("edit_reason") or p.get("delete_reason") or "Cancelled Pharmacy Bill"
            })

        # 2. Investigation Cancelled Bills
        inv_date_clauses = make_date_clauses(["cancelled_date", "date", "created_date"])
        q_inv = {
            "$or": [{"status": "Cancelled"}, {"billing_status": "Cancelled"}, {"is_cancelled": True}]
        }
        if inv_date_clauses:
            q_inv = {"$and": [q_inv, {"$or": inv_date_clauses}]}

        for inv in db["hospital_investbilling"].find(q_inv):
            amt = clean_num(inv.get("total_amount") or inv.get("net_amount") or inv.get("final_amount"))
            dt = inv.get("cancelled_date") or inv.get("date") or inv.get("created_date")
            bno = inv.get("bill_no") or inv.get("bill_number") or str(inv.get("_id"))
            u = str(inv.get("uhid") or "").strip()
            if u:
                uhid_set.add(u)
            rows.append({
                "bill_no": bno,
                "date": format_ist_date(dt),
                "date_raw": dt,
                "category": "Investigation",
                "mr_no": u or "-",
                "patient_name": inv.get("patient_name") or inv.get("patientName") or "",
                "amount": amt,
                "cancelled_by": inv.get("cancelled_by") or "Supervisor",
                "reason": inv.get("cancellation_reason") or inv.get("remarks") or "Investigation Cancelled"
            })

        # 3. Investigation Refunds (Lab, USG, Radiology)
        ir_date_clauses = make_date_clauses(["refundBillDate", "paid_date", "created_date"])
        q_ir = {"$or": ir_date_clauses} if ir_date_clauses else {}
        for ir in db["hospital_investrefund"].find(q_ir):
            amt = clean_num(ir.get("refund_finalPrice") or ir.get("refund_amount") or ir.get("amount"))
            dt = ir.get("refundBillDate") or ir.get("paid_date") or ir.get("created_date")
            bno = ir.get("refundBillNo") or ir.get("investBillNo") or str(ir.get("_id"))
            u = str(ir.get("uhid") or "").strip()
            if u:
                uhid_set.add(u)
            rows.append({
                "bill_no": bno,
                "date": format_ist_date(dt),
                "date_raw": dt,
                "category": f"Refund ({ir.get('billTypeNo') or 'Investigation'})",
                "mr_no": u or "-",
                "patient_name": ir.get("patient_name") or "",
                "amount": amt,
                "cancelled_by": ir.get("CashierID") or ir.get("created_by") or "Cashier",
                "reason": ir.get("refundRemarks") or ir.get("remarks") or "Investigation Refund"
            })

        # 4. General / OP Consultation Refunds
        ref_date_clauses = make_date_clauses(["refund_date", "paid_date", "created_date"])
        q_ref = {"$or": ref_date_clauses} if ref_date_clauses else {}
        for ref in db["hospital_refund"].find(q_ref):
            amt = clean_num(ref.get("refund_amount") or ref.get("amount"))
            dt = ref.get("refund_date") or ref.get("paid_date") or ref.get("created_date")
            bno = ref.get("refund_bill_no") or ref.get("bill_no") or str(ref.get("_id"))
            u = str(ref.get("uhid") or "").strip()
            if u:
                uhid_set.add(u)
            rows.append({
                "bill_no": bno,
                "date": format_ist_date(dt),
                "date_raw": dt,
                "category": "OP Refund",
                "mr_no": u or "-",
                "patient_name": ref.get("patient_name") or "",
                "amount": amt,
                "cancelled_by": ref.get("CashierID") or ref.get("created_by") or "Cashier",
                "reason": ref.get("remarks") or "Consultation / Service Refund"
            })

        # 5. IP Advance Refunds
        ar_date_clauses = make_date_clauses(["refund_date", "created_date"])
        q_ar = {"$or": ar_date_clauses} if ar_date_clauses else {}
        for ar in db["hospital_ipadvance_refund"].find(q_ar):
            amt = clean_num(ar.get("refund_amount") or ar.get("advance_amount"))
            dt = ar.get("refund_date") or ar.get("created_date")
            bno = ar.get("refund_bill_no") or ar.get("bill_no") or str(ar.get("_id"))
            u = str(ar.get("uhid") or "").strip()
            if u:
                uhid_set.add(u)
            rows.append({
                "bill_no": bno,
                "date": format_ist_date(dt),
                "date_raw": dt,
                "category": "IP Advance Refund",
                "mr_no": u or "-",
                "patient_name": ar.get("patient_name") or "",
                "amount": amt,
                "cancelled_by": ar.get("created_by") or "Cashier",
                "reason": ar.get("remarks") or "IP Advance Refund"
            })

        # 5b. Discharge Refunds (hospital_dischargebilling)
        dis_ref_clauses = make_date_clauses(["paid_date", "bill_date", "discharge_date", "created_date"])
        q_dis_ref = {
            "$or": [
                {"payment_details.is_refund": True},
                {"net_amount": {"$lt": 0}}
            ]
        }
        if dis_ref_clauses:
            q_dis_ref = {"$and": [q_dis_ref, {"$or": dis_ref_clauses}]}
        for dr in db["hospital_dischargebilling"].find(q_dis_ref):
            amt = abs(clean_num(dr.get("net_amount") or 0))
            dt = dr.get("paid_date") or dr.get("bill_date") or dr.get("discharge_date") or dr.get("created_date")
            bno = dr.get("bill_no") or dr.get("bill_number") or str(dr.get("_id"))
            u = str(dr.get("uhid") or "").strip()
            if u:
                uhid_set.add(u)
            rows.append({
                "bill_no": bno,
                "date": format_ist_date(dt),
                "date_raw": dt,
                "category": "Discharge Refund",
                "mr_no": u or "-",
                "patient_name": dr.get("patient_name") or "",
                "amount": amt,
                "cancelled_by": dr.get("CashierID") or dr.get("created_by") or "Cashier",
                "reason": "Discharge Settlement Refund"
            })

        # 6. Legacy / Other Hospital Billing
        leg_date_clauses = make_date_clauses(["cancelled_date", "created_date"])
        q_leg = {"$or": [{"status": "Cancelled"}, {"is_cancelled": True}]}
        if leg_date_clauses:
            q_leg = {"$and": [q_leg, {"$or": leg_date_clauses}]}
        for c in db["hospital_billing"].find(q_leg):
            amt = clean_num(c.get("total_fees") or c.get("amount"))
            dt = c.get("cancelled_date") or c.get("created_date")
            bno = c.get("bill_number") or c.get("bill_no") or str(c.get("_id"))
            u = str(c.get("uhid") or "").strip()
            if u:
                uhid_set.add(u)
            rows.append({
                "bill_no": bno,
                "date": format_ist_date(dt),
                "date_raw": dt,
                "category": "Hospital Billing",
                "mr_no": u or "-",
                "patient_name": c.get("patient_name") or "",
                "amount": amt,
                "cancelled_by": c.get("cancelled_by") or "Staff",
                "reason": c.get("cancellation_reason") or "Cancelled by operator"
            })

        # Enrich missing patient names
        if uhid_set:
            patient_name_map = {}
            for p in db["hospital_patient"].find({"uhid": {"$in": list(uhid_set)}}, {"uhid": 1, "firstName": 1, "lastName": 1, "patient_name": 1}):
                fn = (p.get("firstName") or "").strip()
                ln = (p.get("lastName") or "").strip()
                nm = " ".join([x for x in [fn, ln] if x]).strip() or p.get("patient_name") or ""
                patient_name_map[str(p.get("uhid")).strip()] = nm
            for r in rows:
                if not r["patient_name"] and r["mr_no"] in patient_name_map:
                    r["patient_name"] = patient_name_map[r["mr_no"]]
                if not r["patient_name"]:
                    r["patient_name"] = "Patient"

        # Sort by date descending
        rows.sort(key=lambda x: str(x.get("date_raw") or ""), reverse=True)
        for r in rows:
            r.pop("date_raw", None)

        total_val = round(sum(r["amount"] for r in rows), 2)

        return Response({
            "success": True,
            "report_title": "Bill Cancellation Register",
            "count": len(rows),
            "total_cancelled_amount": total_val,
            "data": rows,
            "summary": {
                "total_count": len(rows),
                "total_cancelled_amount": total_val
            }
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass
