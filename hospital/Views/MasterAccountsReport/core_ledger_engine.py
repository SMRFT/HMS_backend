"""
Core Accounting Ledger Engine (Standalone Architecture)
======================================================
Single source of truth for all billing transactions, digital settlements,
advance deposits, sales returns, and counter expense vouchers.

Zero hardcoded maps. Direct PyMongo multi-collection ingestion.
Strict UHID vs IP Number separation. Full mathematical tally.
"""

from pymongo import MongoClient
from datetime import datetime, date, timedelta, timezone
import os

def clean_num(val):
    if val is None or val == "":
        return 0.0
    if hasattr(val, "to_decimal"):
        try:
            return float(val.to_decimal())
        except Exception:
            pass
    try:
        return float(str(val).replace(",", "").strip())
    except Exception:
        return 0.0

def parse_date(date_str, is_end=False):
    if not date_str:
        return None
    s = str(date_str).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(s[:10], fmt)
            if is_end:
                return dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        except Exception:
            continue
    return None

def to_ist(val):
    if not val:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val + timedelta(hours=5, minutes=30)
        return val.astimezone(timezone(timedelta(hours=5, minutes=30)))
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        s = val.strip()
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                return dt + timedelta(hours=5, minutes=30)
            except Exception:
                continue
    return val

def format_dt(val):
    if not val:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%d/%m/%Y %I:%M %p")
    if isinstance(val, date):
        return val.strftime("%d/%m/%Y")
    ist_val = to_ist(val)
    if isinstance(ist_val, datetime):
        return ist_val.strftime("%d/%m/%Y %I:%M %p")
    return str(val)

def format_ist_time(val):
    if not val:
        return ""
    if isinstance(val, str):
        s = val.strip()
        if ("AM" in s.upper() or "PM" in s.upper()) and len(s) <= 10:
            return s
    ist_val = to_ist(val)
    if isinstance(ist_val, datetime):
        return ist_val.strftime("%I:%M %p")
    return str(val or "")

def format_ist_date(val):
    if not val:
        return ""
    ist_val = to_ist(val)
    if isinstance(ist_val, (datetime, date)):
        return ist_val.strftime("%Y-%m-%d")
    return str(val or "")[:10]

def format_ist_datetime(val):
    if not val:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%d/%m/%Y %I:%M %p")
    if isinstance(val, date):
        return val.strftime("%d/%m/%Y")
    ist_val = to_ist(val)
    if isinstance(ist_val, datetime):
        return ist_val.strftime("%d/%m/%Y %I:%M %p")
    return str(val or "")

def split_payment_modes(net_amt, payment_mode, payment_details=None, is_credit_bill=False):
    amt = clean_num(net_amt)
    p_details = payment_details if isinstance(payment_details, dict) else {}
    breakdown = p_details.get("breakdown")
    
    cash = 0.0
    bank = 0.0
    credit = 0.0
    
    if breakdown and isinstance(breakdown, list) and len(breakdown) > 0:
        for b in breakdown:
            if not isinstance(b, dict): continue
            b_amt = clean_num(b.get("Paid_amount") or b.get("amount") or b.get("paid_amount"))
            m = str(b.get("method") or b.get("payment_mode") or "").strip().lower()
            if any(k in m for k in ["bank", "card", "visa", "upi", "pos", "online", "cheque", "neft", "gpay", "phonepe", "paytm"]):
                bank += b_amt
            elif any(k in m for k in ["credit", "scheme", "insurance", "tpa", "cghs", "echs", "esic"]):
                credit += b_amt
            else:
                cash += b_amt
        tot_split = cash + bank + credit
        if tot_split > 0 and abs(tot_split - amt) > 0.01:
            ratio = amt / tot_split
            cash = round(cash * ratio, 2)
            bank = round(bank * ratio, 2)
            credit = round(amt - cash - bank, 2)
        elif tot_split == 0:
            cash = amt
    else:
        m = str(p_details.get("method") or payment_mode or "").strip().lower()
        if is_credit_bill or any(k in m for k in ["credit", "scheme", "insurance", "tpa", "cghs", "echs", "esic"]):
            credit = amt
        elif any(k in m for k in ["bank", "card", "visa", "upi", "pos", "online", "cheque", "neft", "gpay", "phonepe", "paytm"]):
            bank = amt
        else:
            cash = amt
            
    return round(cash, 2), round(credit, 2), round(bank, 2)

def get_db():
    mongo_uri = os.getenv("GLOBAL_DB_HOST")
    client = MongoClient(mongo_uri)
    return client, client["HMS"], client["Global"]

class AccountsLedgerEngine:
    @staticmethod
    def get_ledger_data(from_str=None, to_str=None, outlet_code=None, shift_no=None, category=None):
        client, db, g_db = get_db()
        try:
            # Parse IST Dates
            f_d = parse_date(from_str) if from_str else datetime.now().date()
            t_d = parse_date(to_str, is_end=True) if to_str else datetime.now()
            
            # IST to UTC query bounds (IST = UTC + 5:30)
            f_dt_utc = f_d - timedelta(hours=5, minutes=30)
            t_dt_utc = t_d - timedelta(hours=5, minutes=30)
            
            # 1. Fetch Cash Counter Collections
            ccc_q = {"created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}}
            if outlet_code and str(outlet_code).lower() != "all":
                ccc_q["outlet_code"] = outlet_code
            if shift_no and str(shift_no).lower() != "all":
                ccc_q["shift_no"] = shift_no
            if category and str(category).lower() != "all":
                ccc_q["billing_category"] = category

            ccc_records = list(db["hospital_cashcountercollection"].find(ccc_q).sort("created_date", 1))

            # 2. Extract Bill Numbers for Batch Ingestion
            all_bill_nums = set()
            for r in ccc_records:
                b_no = str(r.get("bill_no") or r.get("bill_number") or "").strip()
                if b_no:
                    all_bill_nums.add(b_no)
                    if "/" in b_no:
                        all_bill_nums.add(b_no.replace("/", ""))
                    elif len(b_no) > 4:
                        all_bill_nums.add(b_no[:4] + "/" + b_no[4:])

            def fetch_doc_map(col_name, query_fields):
                or_clauses = [{f: {"$in": list(all_bill_nums)}} for f in query_fields]
                docs = list(db[col_name].find({"$or": or_clauses}))
                d_map = {}
                for d in docs:
                    for f in query_fields:
                        v = str(d.get(f) or "").strip()
                        if v:
                            d_map[v] = d
                            d_map[v.replace("/", "")] = d
                return d_map

            # Ingest all module collections in parallel batch lookups
            pharm_map = fetch_doc_map("hospital_pharmacybilling", ["bill_no", "Bill_id", "inpatient_number"])
            invest_map = fetch_doc_map("hospital_investbilling", ["investBillNo", "bill_no", "bill_number"])
            billing_map = fetch_doc_map("hospital_billing", ["bill_number", "bill_no"])
            discharge_map = fetch_doc_map("hospital_dischargebilling", ["bill_no", "bill_number"])
            sales_return_map = fetch_doc_map("hospital_salesreturn", ["sales_return_number", "return_no", "bill_no", "Bill_id"])

            # IP Advances in admissions
            advance_map = {}
            adms = list(db["hospital_admission"].find(
                {"advance_payments": {"$exists": True, "$ne": []}},
                {"ipNumber": 1, "uhid": 1, "patient_name": 1, "patientname": 1, "patientName": 1, "advance_payments": 1, "insurance_company": 1, "company_code": 1}
            ))
            for adm in adms:
                for p in (adm.get("advance_payments") or []):
                    if isinstance(p, dict):
                        b = str(p.get("bill_no") or p.get("bill_number") or "").strip()
                        if b:
                            advance_map[b] = {"adm": adm, "pay": p}
                            advance_map[b.replace("/", "")] = {"adm": adm, "pay": p}

            # Bill types map
            billtype_docs = list(db["hospital_billtypes"].find({}, {"billTypeNo": 1, "billTypeName": 1, "bill_type_name": 1}))
            billtype_map = {b.get("billTypeNo"): (b.get("billTypeName") or b.get("bill_type_name")) for b in billtype_docs if b.get("billTypeNo")}

            # Cashier profile map
            cashier_map = {}
            try:
                prof_docs = list(g_db["backend_diagnostics_profile"].find({}, {"employeeId": 1, "employeeName": 1, "_id": 0}))
                cashier_map = {p["employeeId"]: p["employeeName"] for p in prof_docs if p.get("employeeId")}
            except Exception:
                pass

            # Pre-load counter expense vouchers from receiptandpayment
            rp_q = {"created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}, "receipt_type": "Payment"}
            expense_docs = list(db["hospital_receiptandpayment"].find(rp_q).sort("created_date", 1))
            rp_map = {}
            for ep in expense_docs:
                v_no = str(ep.get("voucher_no") or "").strip()
                if v_no:
                    rp_map[v_no] = ep

            # 3. Enrich Every Line Item
            enriched_bills = []
            seen_keys = set()
            
            for r in ccc_records:
                cat = str(r.get("billing_category") or "Unknown").strip()
                b_no = str(r.get("bill_no") or r.get("bill_number") or "").strip()
                
                # Exclude internal handover / remittance records from bill lists
                if cat in ["remitted", "submit"]:
                    continue
                    
                dedup_key = (cat, b_no, r.get("shift_no"), str(r.get("collected_amount")))
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                
                coll_amt = clean_num(r.get("collected_amount"))
                created_dt = r.get("created_date")
                date_ist_str = format_dt(created_dt + timedelta(hours=5, minutes=30)) if isinstance(created_dt, datetime) else str(created_dt or "")
                
                cid = str(r.get("created_by") or "").strip()
                cname = cashier_map.get(cid, cid.upper() or "STAFF")
                
                item_data = {
                    "bill_no": b_no,
                    "date": date_ist_str,
                    "category": cat,
                    "uhid": "",
                    "ip_number": "",
                    "patient_name": "",
                    "gross": coll_amt,
                    "cash": coll_amt,
                    "card": 0.0,
                    "bank": 0.0,
                    "credit": 0.0,
                    "net_amount": coll_amt,
                    "shift_no": r.get("shift_no") or "",
                    "cashier_id": cid,
                    "cashier_name": cname,
                    "payment_mode": r.get("payment_mode") or "CASH",
                    "outlet_code": r.get("outlet_code") or "OLET003",
                    "particulars": []
                }
                
                # Module-specific enrichment
                if cat in ["Pharmacy", "PharmacyBills", "OPPharmacyBills"] and b_no in pharm_map:
                    d = pharm_map[b_no]
                    item_data["category"] = "PHARMACY"
                    item_data["uhid"] = d.get("uhid") or ""
                    item_data["ip_number"] = d.get("inpatient_number") or d.get("ip_no") or ""
                    item_data["patient_name"] = str(d.get("patient_name") or d.get("patientName") or "").strip()
                    amt = clean_num(d.get("net_amount") or coll_amt)
                    pd = d.get("payment_details") or {}
                    pm = pd.get("method") or d.get("payment_method") or r.get("payment_mode") or "Cash"
                    c_val, cr_val, b_val = split_payment_modes(amt, pm, pd)
                    item_data.update({
                        "gross": amt, "net_amount": amt, "amount": amt,
                        "cash": c_val, "credit": cr_val, "bank": b_val,
                        "card": b_val, "card_amount": b_val, "payment_mode": pm,
                        "particulars": d.get("items") or d.get("medicine_particulars") or []
                    })
                    
                elif cat in ["Investigation", "InvestigationBills"] and b_no in invest_map:
                    d = invest_map[b_no]
                    bt_no = d.get("billTypeNo")
                    disp_type = billtype_map.get(bt_no) or "Investigation"
                    if "(SH)" not in disp_type: disp_type = f"{disp_type} (SH)"
                    item_data["category"] = disp_type
                    item_data["uhid"] = d.get("uhid") or ""
                    item_data["ip_number"] = d.get("ipNumber") or d.get("ip_number") or ""
                    item_data["patient_name"] = str(d.get("patient_name") or d.get("patientname") or "").strip()
                    amt = clean_num(d.get("finalPrice") or d.get("total") or coll_amt)
                    pd = d.get("payment_details") or {}
                    pm = pd.get("method") or d.get("payment_method") or r.get("payment_mode") or "Cash"
                    c_val, cr_val, b_val = split_payment_modes(amt, pm, pd)
                    item_data.update({
                        "gross": amt, "net_amount": amt, "amount": amt,
                        "cash": c_val, "credit": cr_val, "bank": b_val,
                        "card": b_val, "card_amount": b_val, "payment_mode": pm,
                        "particulars": d.get("item") or []
                    })
                    
                elif cat in ["Billing", "Registration", "RegistrationBills"] and b_no in billing_map:
                    d = billing_map[b_no]
                    item_data["category"] = "REGISTRATION"
                    item_data["uhid"] = d.get("uhid") or ""
                    item_data["patient_name"] = str(d.get("patient_name") or d.get("patientname") or "").strip()
                    amt = clean_num(d.get("total_fees") or coll_amt)
                    pd = d.get("payment_details") or {}
                    pm = pd.get("method") or d.get("payment_mode") or r.get("payment_mode") or "Cash"
                    c_val, cr_val, b_val = split_payment_modes(amt, pm, pd)
                    item_data.update({
                        "gross": amt, "net_amount": amt, "amount": amt,
                        "cash": c_val, "credit": cr_val, "bank": b_val,
                        "card": b_val, "card_amount": b_val, "payment_mode": pm,
                        "particulars": d.get("items") or []
                    })
                    
                elif cat in ["Discharge", "DischargeBills"] and b_no in discharge_map:
                    d = discharge_map[b_no]
                    item_data["category"] = "DISCHARGE"
                    item_data["uhid"] = d.get("uhid") or ""
                    item_data["ip_number"] = d.get("ip_number") or d.get("ipNumber") or ""
                    item_data["patient_name"] = str(d.get("patient_name") or d.get("patientname") or "").strip()
                    
                    tot_gross = clean_num(d.get("total_amount") or d.get("gross_amount"))
                    adv_adj = clean_num(d.get("advance_amount") or d.get("advance_adjustment"))
                    net_paid = clean_num(d.get("net_amount") or coll_amt)
                    if tot_gross == 0.0:
                        tot_gross = net_paid + adv_adj
                        
                    pd = d.get("payment_details") or {}
                    pm = pd.get("method") or d.get("payment_mode") or r.get("payment_mode") or "Cash"
                    c_val, cr_val, b_val = split_payment_modes(net_paid, pm, pd)
                    
                    # Decompose departmental charges from line items
                    items = d.get("items") or []
                    room_c, nursing_c, doctor_c, lab_c = 0.0, 0.0, 0.0, 0.0
                    pharm_c = clean_num(d.get("medicines_amount") or 0.0)
                    for it in items:
                        if not isinstance(it, dict): continue
                        it_amt = clean_num(it.get("amount") or it.get("rate"))
                        it_name = str(it.get("itemName") or "").upper()
                        bt_no = str(it.get("billTypeNo") or "").upper()
                        if "ROOM" in it_name or "BED" in it_name: room_c += it_amt
                        elif "NURS" in it_name: nursing_c += it_amt
                        elif any(k in it_name for k in ["DR", "DOCTOR", "FEE", "CONSULT"]): doctor_c += it_amt
                        elif "LAB" in bt_no or any(k in it_name for k in ["LAB", "TEST", "BLOOD", "URINE", "SCAN", "X-RAY"]): lab_c += it_amt
                        elif "PHARM" in bt_no or "MEDICINE" in it_name: pharm_c += it_amt

                    item_data.update({
                        "gross": tot_gross, "gross_amount": tot_gross,
                        "advance_adjustment": adv_adj, "advance_amount": adv_adj,
                        "net_paid": net_paid, "net_amount": net_paid, "amount": net_paid,
                        "cash": c_val, "credit": cr_val, "bank": b_val,
                        "card": b_val, "card_amount": b_val, "payment_mode": pm,
                        "room_charges": round(room_c, 2), "nursing_charges": round(nursing_c, 2),
                        "doctor_charges": round(doctor_c, 2), "doctor_fees": round(doctor_c, 2),
                        "lab_charges": round(lab_c, 2), "pharmacy_charges": round(pharm_c, 2),
                        "particulars": items
                    })
                    
                elif cat in ["IPAdvance", "IPAdvanceBills", "IPAdvance Payment", "Advance", "advance"] or (b_no in advance_map):
                    adv_info = advance_map.get(b_no) or advance_map.get(b_no.replace("/", ""))
                    item_data["category"] = "ADVANCE"
                    if adv_info:
                        adm = adv_info["adm"]
                        pay = adv_info["pay"]
                        item_data["uhid"] = adm.get("uhid") or ""
                        item_data["ip_number"] = adm.get("ipNumber") or ""
                        item_data["patient_name"] = str(pay.get("patient_name") or adm.get("patient_name") or adm.get("patientname") or "").strip()
                        amt = clean_num(pay.get("advance_amount") or pay.get("amount") or coll_amt)
                        pd = pay.get("payment_details") or {}
                        pm = pd.get("method") or pay.get("payment_mode") or r.get("payment_mode") or "Cash"
                        c_val, cr_val, b_val = split_payment_modes(amt, pm, pd)
                        item_data.update({
                            "gross": amt, "net_amount": amt, "amount": amt, "advance_amount": amt,
                            "cash": c_val, "credit": cr_val, "bank": b_val,
                            "card": b_val, "card_amount": b_val, "payment_mode": pm
                        })
                    else:
                        pm = r.get("payment_mode") or "Cash"
                        c_val, cr_val, b_val = split_payment_modes(coll_amt, pm)
                        item_data.update({
                            "gross": coll_amt, "net_amount": coll_amt, "amount": coll_amt, "advance_amount": coll_amt,
                            "cash": c_val, "credit": cr_val, "bank": b_val,
                            "card": b_val, "card_amount": b_val, "payment_mode": pm
                        })

                elif cat in ["Sales Return", "sales_return", "SalesReturn"]:
                    d = sales_return_map.get(b_no) or sales_return_map.get(r.get("return_bill_no")) or {}
                    ret_amt = clean_num(d.get("return_amount") or r.get("Returned_amount") or coll_amt)
                    item_data["category"] = "Sales Return"
                    item_data["uhid"] = d.get("uhid") or ""
                    pm = d.get("PaymentType") or r.get("payment_mode") or "Cash"
                    c_val, cr_val, b_val = split_payment_modes(ret_amt, pm)
                    item_data.update({
                        "gross": -ret_amt, "net_amount": -ret_amt,
                        "cash": -c_val, "credit": -cr_val, "bank": -b_val,
                        "card": -b_val, "card_amount": b_val,
                        "amount": ret_amt, "return_amount": ret_amt, "sales_return": ret_amt,
                        "payment_mode": pm,
                        "particulars": d.get("medicine_particulars") or []
                    })
                        
                elif cat in ["Receipt", "Payment"]:
                    if cat == "Payment":
                        ep = rp_map.get(b_no) or {}
                        pay_amt = clean_num(ep.get("amount") or r.get("Returned_amount") or coll_amt)
                        
                        raw_rem = r.get("remarks") or ep.get("description") or ""
                        pt_name = ""
                        room_str = ""
                        desc_str = ""
                        if isinstance(raw_rem, str) and raw_rem.strip().startswith("{") and raw_rem.strip().endswith("}"):
                            try:
                                import json
                                pj = json.loads(raw_rem)
                                pt_name = str(pj.get("patient_name") or "").strip()
                                room_str = str(pj.get("room_no") or "").strip()
                                desc_str = str(pj.get("description") or "").strip()
                            except Exception:
                                desc_str = raw_rem
                        elif isinstance(raw_rem, dict):
                            pt_name = str(raw_rem.get("patient_name") or "").strip()
                            room_str = str(raw_rem.get("room_no") or "").strip()
                            desc_str = str(raw_rem.get("description") or "").strip()
                        else:
                            desc_str = str(raw_rem or "").strip()

                        display_name = (pt_name + (f" (Room {room_str})" if room_str else "")) if pt_name else (desc_str or ep.get("account_head") or "Counter Expense Payment")
                        part_item = f"Room {room_str}" if (room_str and pt_name) else (desc_str or "Counter Payment Voucher")

                        item_data.update({
                            "category": "EXPENSE PAYMENT",
                            "patient_name": display_name,
                            "gross": -pay_amt,
                            "amount": pay_amt,
                            "expense_amount": pay_amt,
                            "cash": -pay_amt,
                            "net_amount": -pay_amt,
                            "is_expense": True,
                            "payment_mode": "Cash",
                            "particulars": [{"itemName": part_item}]
                        })
                    else:
                        item_data["category"] = "MISCELLANEOUS INCOME"
                        item_data["cash"] = coll_amt
                        item_data["amount"] = coll_amt
                        item_data["payment_mode"] = "Cash"

                elif cat in ["refund", "Refund", "Discharge Refund"] or str(r.get("transaction_type") or "").lower() == "refund":
                    ref_amt = clean_num(r.get("Returned_amount") or coll_amt)
                    rem_text = str(r.get("remarks") or "Discharge Refund").strip()
                    item_data.update({
                        "category": "REFUND",
                        "patient_name": rem_text,
                        "gross": -ref_amt,
                        "amount": ref_amt,
                        "sales_return_amount": ref_amt,
                        "refund_amount": ref_amt,
                        "cash": -ref_amt,
                        "net_amount": -ref_amt,
                        "is_sales_return": True,
                        "is_refund": True,
                        "payment_mode": "Cash",
                        "particulars": [{"itemName": rem_text}]
                    })

                enriched_bills.append(item_data)

            # 4. Universal Patient Master Backfill Pass
            missing_uhids = list(set([b["uhid"] for b in enriched_bills if b.get("uhid") and not b.get("patient_name")]))
            if missing_uhids:
                p_docs = list(db["hospital_patient"].find({"uhid": {"$in": missing_uhids}}, {"uhid": 1, "firstName": 1, "lastName": 1}))
                p_map = {p["uhid"]: f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() for p in p_docs}
                
                # Also check patient registration collection
                reg_docs = list(db["hospital_patientregistration"].find(
                    {"$or": [{"uhid": {"$in": missing_uhids}}, {"PatientId": {"$in": missing_uhids}}]},
                    {"PatientId": 1, "uhid": 1, "firstName": 1, "middleName": 1, "lastName": 1}
                ))
                for pr in reg_docs:
                    uid = str(pr.get("uhid") or pr.get("PatientId") or "").strip()
                    if uid and uid not in p_map:
                        full_name = " ".join([x for x in [(pr.get("firstName") or "").strip(), (pr.get("middleName") or "").strip(), (pr.get("lastName") or "").strip()] if x]).strip()
                        if full_name:
                            p_map[uid] = full_name

                for b in enriched_bills:
                    if b.get("uhid") and not b.get("patient_name") and b["uhid"] in p_map:
                        b["patient_name"] = p_map[b["uhid"]]

            # Clean UHID and IP number separation
            for b in enriched_bills:
                u = str(b.get("uhid") or "").strip()
                ip = str(b.get("ip_number") or "").strip()
                if ip == u:
                    ip = ""
                b["uhid"] = u
                b["mr_no"] = u if u else "—"
                b["ip_number"] = ip
                if not b.get("patient_name"):
                    b["patient_name"] = f"Patient #{u}" if u else "General Patient"

            # 5. Fetch Counter Expense Vouchers (Payment receipts)
            expense_vouchers = []
            total_counter_expenses = 0.0
            
            for ep in expense_docs:
                e_amt = clean_num(ep.get("amount") or 0.0)
                total_counter_expenses += e_amt
                ep_dt = ep.get("created_date")
                ep_dt_str = format_dt(ep_dt + timedelta(hours=5, minutes=30)) if isinstance(ep_dt, datetime) else str(ep_dt or "")
                cid = str(ep.get("created_by") or "").strip()
                
                desc_raw = ep.get("description") or ""
                pt_n = ""
                rm_n = ""
                ds_t = ""
                if isinstance(desc_raw, str) and desc_raw.strip().startswith("{") and desc_raw.strip().endswith("}"):
                    try:
                        import json
                        pj = json.loads(desc_raw)
                        pt_n = str(pj.get("patient_name") or "").strip()
                        rm_n = str(pj.get("room_no") or "").strip()
                        ds_t = str(pj.get("description") or "").strip()
                    except Exception:
                        ds_t = desc_raw
                elif isinstance(desc_raw, dict):
                    pt_n = str(desc_raw.get("patient_name") or "").strip()
                    rm_n = str(desc_raw.get("room_no") or "").strip()
                    ds_t = str(desc_raw.get("description") or "").strip()
                else:
                    ds_t = str(desc_raw or "")
                    
                final_desc = (pt_n + (f" (Room {rm_n})" if rm_n else "")) if pt_n else (ds_t or "Counter Expense Payment")
                
                expense_vouchers.append({
                    "voucher_no": ep.get("voucher_no") or "—",
                    "date": ep_dt_str,
                    "amount": e_amt,
                    "account_head": str(ep.get("account_head") or "Counter Expense"),
                    "description": final_desc,
                    "shift_no": ep.get("shiftno") or "",
                    "cashier_id": cid,
                    "cashier_name": cashier_map.get(cid, cid.upper() or "STAFF")
                })

            # 6. Shift-Wise Handover Reconciliation & Comprehensive Return Resolution
            shift_q = {"date": {"$gte": f_d, "$lte": t_d}}
            if outlet_code and str(outlet_code).lower() != "all":
                shift_q["$or"] = [{"outlet_code": outlet_code}, {"SelectedOutlet": outlet_code}]
            shifts_in_db = list(db["hospital_cashcountershiftdetails"].find(shift_q).sort("shiftno", 1))

            # Ingest Sales Returns directly from hospital_salesreturn to guarantee no return is omitted
            known_sr_shift_nos = [str(s.get("shiftno") or "").strip() for s in shifts_in_db if s.get("shiftno")]
            sr_query_clauses = [
                {"created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
                {"return_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
                {"paid_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
            ]
            if known_sr_shift_nos:
                sr_query_clauses.extend([
                    {"shiftno": {"$in": known_sr_shift_nos}},
                    {"shift_no": {"$in": known_sr_shift_nos}}
                ])
            sr_find_q = {"$or": sr_query_clauses}
            if outlet_code and str(outlet_code).lower() != "all":
                sr_find_q["outlet_code"] = outlet_code
            sr_docs = list(db["hospital_salesreturn"].find(sr_find_q))

            seen_sr_keys = {str(b.get("bill_no") or "").strip() for b in enriched_bills if b.get("is_sales_return") or b.get("category") == "Sales Return"}
            for sr in sr_docs:
                sr_ret_no = str(sr.get("return_bill_no") or "").strip()
                sr_orig_no = str(sr.get("bill_no") or "").strip()
                if (sr_ret_no and sr_ret_no in seen_sr_keys) or (sr_orig_no and sr_orig_no in seen_sr_keys):
                    continue
                if sr_ret_no:
                    seen_sr_keys.add(sr_ret_no)
                if sr_orig_no:
                    seen_sr_keys.add(sr_orig_no)

                # Match to appropriate shift
                r_shift = str(sr.get("shiftno") or sr.get("shift_no") or "").strip()
                rc_dt = sr.get("created_date") or sr.get("return_date")
                r_outlet = str(sr.get("outlet_code") or "").strip()
                if not r_shift and isinstance(rc_dt, datetime):
                    for sh in shifts_in_db:
                        sh_outlet = str(sh.get("SelectedOutlet") or sh.get("outlet_code") or "").strip()
                        if not r_outlet or sh_outlet == r_outlet:
                            sh_start = sh.get("StartingTime")
                            sh_end = sh.get("closingTime") or (sh_start + timedelta(hours=14) if sh_start else None)
                            if sh_start and sh_end and (sh_start <= rc_dt <= sh_end):
                                r_shift = str(sh.get("shiftno") or "").strip()
                                break

                r_amt = clean_num(sr.get("return_amount") or sr.get("total_amount") or sr.get("net_amount") or sr.get("amount"))
                pm = str(sr.get("PaymentType") or sr.get("payment_mode") or "Cash").strip()
                c_val, cr_val, b_val = split_payment_modes(r_amt, pm)

                sr_dt_str = format_dt(rc_dt + timedelta(hours=5, minutes=30)) if isinstance(rc_dt, datetime) else str(rc_dt or "")
                sr_cid = str(sr.get("pharmacist_id") or sr.get("CashierID") or sr.get("created_by") or "")
                sr_cname = cashier_map.get(sr_cid, sr_cid.upper() or "PHARMACY")

                enriched_bills.append({
                    "bill_no": sr_ret_no or sr_orig_no or "RET",
                    "date": sr_dt_str,
                    "category": "Sales Return",
                    "uhid": str(sr.get("uhid") or ""),
                    "ip_number": "",
                    "patient_name": "Sales Return - Pharmacy",
                    "gross": -r_amt,
                    "cash": -c_val,
                    "card": -b_val,
                    "bank": -b_val,
                    "credit": -cr_val,
                    "net_amount": -r_amt,
                    "amount": r_amt,
                    "return_amount": r_amt,
                    "sales_return": r_amt,
                    "shift_no": r_shift,
                    "cashier_id": sr_cid,
                    "cashier_name": sr_cname,
                    "payment_mode": pm,
                    "outlet_code": r_outlet or "OLET002",
                    "particulars": sr.get("medicine_particulars") or [],
                    "is_sales_return": True
                })

            shift_reconciliation = []
            for s in shifts_in_db:
                s_no = str(s.get("shiftno") or "").strip()
                c_id = s.get("CashierID")
                c_name = cashier_map.get(c_id, c_id)
                s_dt = s.get("date")
                if isinstance(s_dt, (datetime, date)):
                    s_dt_str = s_dt.strftime("%Y-%m-%d")
                elif s_dt:
                    s_dt_str = str(s_dt)[:10]
                else:
                    s_dt_str = ""
                
                s_no_clean = s_no.replace("/", "")
                s_cash_gross = sum(b["cash"] for b in enriched_bills if (str(b.get("shift_no") or "").strip() == s_no or str(b.get("shift_no") or "").replace("/", "").strip() == s_no_clean) and b["cash"] > 0)
                s_card_amt = sum(b["bank"] for b in enriched_bills if (str(b.get("shift_no") or "").strip() == s_no or str(b.get("shift_no") or "").replace("/", "").strip() == s_no_clean))
                s_credit_amt = sum(b["credit"] for b in enriched_bills if (str(b.get("shift_no") or "").strip() == s_no or str(b.get("shift_no") or "").replace("/", "").strip() == s_no_clean))
                s_expenses = sum(v["amount"] for v in expense_vouchers if (str(v.get("shift_no") or "").strip() == s_no or str(v.get("shift_no") or "").replace("/", "").strip() == s_no_clean))

                s_returns_bills = sum(b.get("return_amount", 0) for b in enriched_bills if (str(b.get("shift_no") or "").strip() == s_no or str(b.get("shift_no") or "").replace("/", "").strip() == s_no_clean) and (b.get("category") == "Sales Return" or b.get("sales_return", 0) > 0 or b.get("is_sales_return")))
                s_refunds_bills = sum(b.get("refund_amount", 0) for b in enriched_bills if (str(b.get("shift_no") or "").strip() == s_no or str(b.get("shift_no") or "").replace("/", "").strip() == s_no_clean) and (b.get("category") == "REFUND" or b.get("is_refund")))

                s_stored_ret = clean_num(s.get("SalesReturnAmount"))
                s_returns = round(max(s_returns_bills + s_refunds_bills, s_stored_ret), 2)
                s_net_handover = round(s_cash_gross - s_expenses - s_returns, 2)
                
                recorded_cash = clean_num(s.get("collected_Amount"))
                recorded_credit = clean_num(s.get("CreditAmount"))
                
                shift_reconciliation.append({
                    "shift_no": s_no,
                    "date": s_dt_str,
                    "cashier_id": c_id,
                    "cashier_name": c_name,
                    "SelectedOutlet": s.get("SelectedOutlet") or s.get("outlet_code") or "OLET003",
                    "start_time": format_ist_time(s.get("StartingTime") or s.get("StartTime")) or "08:00 AM",
                    "end_time": format_ist_time(s.get("closingTime") or s.get("EndTime")) if (s.get("closingTime") or s.get("EndTime")) else "Active",
                    "shift_status": s.get("ShiftStatus") or "closed",
                    "gross_cash": round(s_cash_gross, 2),
                    "expenses_paid": round(s_expenses, 2),
                    "sales_return": round(s_returns, 2),
                    "retAmt": round(s_returns, 2),
                    "net_handover_cash": s_net_handover,
                    "recorded_shift_cash": recorded_cash,
                    "card_collection": round(s_card_amt, 2),
                    "credit_collection": round(s_credit_amt, 2),
                    "recorded_credit": recorded_credit,
                    "opening_balance": clean_num(s.get("OpeningBalance")),
                    "closing_balance": clean_num(s.get("ClosingBalance")),
                    "is_tallied": (abs(s_net_handover - recorded_cash) < 0.01) or (abs(s_cash_gross - recorded_cash) < 0.01)
                })

            # 7. Financial Grand Totals
            total_gross_cash = round(sum(b["cash"] for b in enriched_bills if b["cash"] > 0), 2)
            total_bank_card = round(sum(b["bank"] for b in enriched_bills), 2)
            total_credit_scheme = round(sum(b["credit"] for b in enriched_bills), 2)
            total_gross_revenue = round(total_gross_cash + total_bank_card + total_credit_scheme, 2)
            total_sales_returns = round(sum(s["sales_return"] for s in shift_reconciliation), 2)
            net_cash_handover = round(total_gross_cash - total_counter_expenses - total_sales_returns, 2)

            return {
                "success": True,
                "date_range": {"from_date": str(f_d)[:10], "to_date": str(t_d)[:10]},
                "financial_summary": {
                    "gross_cash_collections": total_gross_cash,
                    "total_gross_cash": total_gross_cash,
                    "total_cash": total_gross_cash,
                    "counter_expenses_paid": total_counter_expenses,
                    "total_expenses_paid": total_counter_expenses,
                    "expenses_paid": total_counter_expenses,
                    "net_cash_handover": net_cash_handover,
                    "total_net_handover": net_cash_handover,
                    "net_handover_cash": net_cash_handover,
                    "total_recorded_cash": total_gross_cash,
                    "card_and_bank_collections": total_bank_card,
                    "total_card_collection": total_bank_card,
                    "total_card": total_bank_card,
                    "total_card_amount": total_bank_card,
                    "credit_and_insurance_collections": total_credit_scheme,
                    "total_credit_collection": total_credit_scheme,
                    "total_credit": total_credit_scheme,
                    "total_credit_amount": total_credit_scheme,
                    "total_gross_revenue": total_gross_revenue,
                    "grand_total": total_gross_revenue,
                    "total_revenue": total_gross_revenue,
                    "total_collection": total_gross_revenue,
                    "net_collection": total_gross_revenue,
                    "total_advance": round(sum(b["gross"] for b in enriched_bills if b["category"] == "ADVANCE"), 2),
                    "total_settlement": round(sum(b["gross"] for b in enriched_bills if b["category"] == "DISCHARGE"), 2),
                    "total_sales_returns": total_sales_returns,
                    "sales_returns": total_sales_returns,
                    "sales_return": total_sales_returns,
                    "formula": "Net Cash Hand Over = Gross Cash Collections - Counter Expense Payments - Sales Returns"
                },
                "bills": enriched_bills,
                "expense_vouchers": expense_vouchers,
                "shift_reconciliation": shift_reconciliation,
                "counts": {
                    "total_bills": len(enriched_bills),
                    "total_expenses": len(expense_vouchers),
                    "total_shifts": len(shift_reconciliation)
                }
            }
        finally:
            client.close()
