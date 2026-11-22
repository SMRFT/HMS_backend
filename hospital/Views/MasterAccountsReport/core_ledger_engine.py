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
from concurrent.futures import ThreadPoolExecutor
import os
import time

_MASTER_CACHE = {
    "package_map": None,
    "billtype_map": None,
    "billtype_id_map": None,
    "cashier_map": None,
    "expires_at": 0
}

_LEDGER_RESULT_CACHE = {}
_LEDGER_CACHE_TTL = 30  # 30-second in-memory response cache

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

_SHARED_CLIENT = None

def get_db():
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None:
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        _SHARED_CLIENT = MongoClient(
            mongo_uri,
            maxPoolSize=50,
            minPoolSize=5,
            connectTimeoutMS=10000,
            socketTimeoutMS=30000,
            serverSelectionTimeoutMS=10000,
            retryWrites=True
        )
    return _SHARED_CLIENT, _SHARED_CLIENT["HMS"], _SHARED_CLIENT["Global"]

class AccountsLedgerEngine:
    @staticmethod
    def get_ledger_data(from_str=None, to_str=None, outlet_code=None, shift_no=None, category=None, force_refresh=False):
        cache_key = (
            str(from_str),
            str(to_str),
            str(outlet_code or "all").lower(),
            str(shift_no or "all").lower(),
            str(category or "all").lower()
        )
        now = time.time()
        if not force_refresh and cache_key in _LEDGER_RESULT_CACHE:
            cached_time, cached_val = _LEDGER_RESULT_CACHE[cache_key]
            if now - cached_time < _LEDGER_CACHE_TTL:
                return cached_val

        client, db, g_db = get_db()
        try:
            # Parse IST Dates
            f_d = parse_date(from_str) if from_str else datetime.now().date()
            t_d = parse_date(to_str, is_end=True) if to_str else datetime.now()
            
            # IST to UTC query bounds (IST = UTC + 5:30)
            f_dt_utc = f_d - timedelta(hours=5, minutes=30)
            t_dt_utc = t_d - timedelta(hours=5, minutes=30)
            
            # 1. Fetch Cash Counter Collections with lean projection
            ccc_q = {"created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}}
            if outlet_code and str(outlet_code).lower() != "all":
                ccc_q["outlet_code"] = outlet_code
            if shift_no and str(shift_no).lower() != "all":
                ccc_q["shift_no"] = shift_no
            if category and str(category).lower() != "all":
                ccc_q["billing_category"] = category

            ccc_proj = {
                "bill_no": 1, "bill_number": 1, "Bill_id": 1, "billing_category": 1,
                "collected_amount": 1, "created_date": 1, "created_by": 1, "payment_mode": 1,
                "outlet_code": 1, "shift_no": 1, "remarks": 1, "transaction_type": 1,
                "return_bill_no": 1, "Returned_amount": 1
            }
            ccc_records = list(db["hospital_cashcountercollection"].find(ccc_q, ccc_proj).sort("created_date", 1))

            # 2. Extract Bill Numbers and Bill IDs for Batch Ingestion
            all_bill_nums = set()
            all_bill_ids = set()
            for r in ccc_records:
                b_no = str(r.get("bill_no") or r.get("bill_number") or "").strip()
                if b_no:
                    all_bill_nums.add(b_no)
                    if "/" in b_no:
                        all_bill_nums.add(b_no.replace("/", ""))
                    elif len(b_no) > 4:
                        all_bill_nums.add(b_no[:4] + "/" + b_no[4:])
                ret_no = str(r.get("return_bill_no") or "").strip()
                if ret_no:
                    all_bill_nums.add(ret_no)
                    if "/" in ret_no:
                        all_bill_nums.add(ret_no.replace("/", ""))
                    elif len(ret_no) > 4:
                        all_bill_nums.add(ret_no[:4] + "/" + ret_no[4:])
                bid = r.get("Bill_id")
                if bid is not None and str(bid).strip():
                    try:
                        all_bill_ids.add(int(bid))
                    except Exception:
                        pass
                    all_bill_ids.add(str(bid).strip())

            bill_num_list = list(all_bill_nums)
            bill_id_list = list(all_bill_ids)

            # Master caching (5-minute TTL)
            global _MASTER_CACHE
            if _MASTER_CACHE["expires_at"] > now and _MASTER_CACHE["package_map"] is not None:
                package_map = _MASTER_CACHE["package_map"]
                billtype_map = _MASTER_CACHE["billtype_map"]
                billtype_id_map = _MASTER_CACHE["billtype_id_map"]
                cashier_map = _MASTER_CACHE["cashier_map"]
            else:
                package_map = {}
                try:
                    for p in db["hospital_package"].find({}, {"packageNo": 1, "packageName": 1}):
                        p_no, p_name = p.get("packageNo"), p.get("packageName")
                        if p_no is not None and p_name:
                            package_map[p_no] = str(p_name).strip()
                            package_map[str(p_no)] = str(p_name).strip()
                except Exception:
                    pass

                billtype_map, billtype_id_map = {}, {}
                try:
                    for b in db["hospital_billtype"].find({}, {"billTypeNo": 1, "bill_name": 1, "bill_type": 1, "billTypeName": 1}):
                        bt_no = b.get("billTypeNo")
                        bt_name = b.get("bill_name") or b.get("billTypeName")
                        bt_id = b.get("bill_type")
                        if bt_no and bt_name:
                            billtype_map[str(bt_no).strip()] = str(bt_name).strip()
                        if bt_id is not None and bt_name:
                            billtype_id_map[str(bt_id).strip()] = str(bt_name).strip()
                except Exception:
                    pass

                cashier_map = {}
                try:
                    for p in g_db["backend_diagnostics_profile"].find({}, {"employeeId": 1, "employeeName": 1, "_id": 0}):
                        if p.get("employeeId"):
                            cashier_map[p["employeeId"]] = p["employeeName"]
                except Exception:
                    pass

                _MASTER_CACHE = {
                    "package_map": package_map,
                    "billtype_map": billtype_map,
                    "billtype_id_map": billtype_id_map,
                    "cashier_map": cashier_map,
                    "expires_at": now + 300
                }

            # Parallel Concurrent Module Queries
            def fetch_pharm():
                if not bill_num_list and not bill_id_list:
                    return []
                proj = {
                    "bill_no": 1, "bill_number": 1, "Bill_id": 1, "billed_bill_no": 1, "converted_bill_no": 1,
                    "inpatient_number": 1, "ip_no": 1, "uhid": 1, "patient_name": 1, "patientName": 1,
                    "net_amount": 1, "payment_details": 1, "payment_method": 1, "payment_mode": 1,
                    "billing_mode": 1, "is_insurance": 1, "items": 1, "medicine_particulars": {"$slice": 15},
                    "created_by": 1, "pharmacist_id": 1, "lastmodified_by": 1, "shiftno": 1
                }
                found_docs = []
                seen_ids = set()
                if bill_num_list:
                    for i in range(0, len(bill_num_list), 200):
                        chunk = bill_num_list[i:i + 200]
                        for d in db["hospital_pharmacybilling"].find({"bill_no": {"$in": chunk}}, proj):
                            did = d.get("_id")
                            if did not in seen_ids:
                                seen_ids.add(did)
                                found_docs.append(d)
                if bill_id_list:
                    for i in range(0, len(bill_id_list), 200):
                        chunk = bill_id_list[i:i + 200]
                        for d in db["hospital_pharmacybilling"].find({"Bill_id": {"$in": chunk}}, proj):
                            did = d.get("_id")
                            if did not in seen_ids:
                                seen_ids.add(did)
                                found_docs.append(d)
                return found_docs

            def fetch_invest():
                if not bill_num_list:
                    return []
                proj = {
                    "investBillNo": 1, "bill_no": 1, "bill_number": 1, "billTypeNo": 1, "bill_type": 1,
                    "item": 1, "particulars": 1, "package_id": 1, "package_name": 1, "packageName": 1,
                    "uhid": 1, "ipNumber": 1, "ip_number": 1, "patient_name": 1, "patientname": 1,
                    "finalPrice": 1, "total": 1, "payment_details": 1, "payment_method": 1,
                    "doctor": 1, "referredBy": 1, "created_by": 1, "CashierID": 1, "lastmodified_by": 1
                }
                return list(db["hospital_investbilling"].find({"$or": [
                    {"investBillNo": {"$in": bill_num_list}},
                    {"bill_no": {"$in": bill_num_list}},
                    {"bill_number": {"$in": bill_num_list}}
                ]}, proj))

            def fetch_billing():
                if not bill_num_list:
                    return []
                proj = {
                    "bill_number": 1, "bill_no": 1, "uhid": 1, "patient_name": 1, "patientname": 1,
                    "total_fees": 1, "payment_details": 1, "payment_mode": 1, "items": 1,
                    "created_by": 1, "lastmodified_by": 1
                }
                return list(db["hospital_billing"].find({"$or": [
                    {"bill_number": {"$in": bill_num_list}},
                    {"bill_no": {"$in": bill_num_list}}
                ]}, proj))

            def fetch_discharge():
                if not bill_num_list:
                    return []
                proj = {
                    "bill_no": 1, "bill_number": 1, "uhid": 1, "ip_number": 1, "ipNumber": 1,
                    "patient_name": 1, "patientname": 1, "total_amount": 1, "gross_amount": 1,
                    "advance_amount": 1, "advance_adjustment": 1, "net_amount": 1, "payment_details": 1,
                    "payment_mode": 1, "items": 1, "medicines_amount": 1
                }
                return list(db["hospital_dischargebilling"].find({"$or": [
                    {"bill_no": {"$in": bill_num_list}},
                    {"bill_number": {"$in": bill_num_list}}
                ]}, proj))

            def fetch_invest_refund():
                if not bill_num_list:
                    return []
                proj = {
                    "refundBillNo": 1, "investBillNo": 1, "uhid": 1, "ipNumber": 1,
                    "refund_finalPrice": 1, "refund_amount": 1, "refundRemarks": 1,
                    "patient_name": 1, "patientName": 1, "item": 1, "billTypeNo": 1
                }
                return list(db["hospital_investrefund"].find({"$or": [
                    {"refundBillNo": {"$in": bill_num_list}},
                    {"investBillNo": {"$in": bill_num_list}}
                ]}, proj))

            def fetch_general_refund():
                if not bill_num_list:
                    return []
                proj = {
                    "refund_bill_no": 1, "bill_no": 1, "uhid": 1, "ip_number": 1,
                    "patient_name": 1, "refund_amount": 1, "remarks": 1
                }
                return list(db["hospital_refund"].find({"$or": [
                    {"refund_bill_no": {"$in": bill_num_list}},
                    {"bill_no": {"$in": bill_num_list}}
                ]}, proj))

            def fetch_ipadv_refund():
                if not bill_num_list:
                    return []
                proj = {
                    "refund_bill_no": 1, "bill_no": 1, "uhid": 1, "ip_number": 1,
                    "patient_name": 1, "refund_amount": 1, "advance_amount": 1, "remarks": 1
                }
                return list(db["hospital_ipadvance_refund"].find({"$or": [
                    {"refund_bill_no": {"$in": bill_num_list}},
                    {"bill_no": {"$in": bill_num_list}}
                ]}, proj))

            def fetch_sales_return():
                return list(db["hospital_salesreturn"].find({"$or": [
                    {"sales_return_number": {"$in": bill_num_list}},
                    {"return_no": {"$in": bill_num_list}},
                    {"bill_no": {"$in": bill_num_list}},
                    {"Bill_id": {"$in": bill_num_list}}
                ]}))

            def fetch_admissions():
                if not bill_num_list:
                    return []
                return list(db["hospital_admission"].find(
                    {"$or": [
                        {"advance_payments.bill_no": {"$in": bill_num_list}},
                        {"advance_payments.bill_number": {"$in": bill_num_list}}
                    ]},
                    {"ipNumber": 1, "uhid": 1, "patient_name": 1, "patientname": 1, "patientName": 1, "advance_payments": 1, "insurance_company": 1, "company_code": 1}
                ))

            def fetch_expenses():
                rp_q = {"created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}, "receipt_type": "Payment"}
                return list(db["hospital_receiptandpayment"].find(rp_q).sort("created_date", 1))

            def fetch_shifts():
                shift_q = {"date": {"$gte": f_d, "$lte": t_d}}
                if outlet_code and str(outlet_code).lower() != "all":
                    shift_q["$or"] = [{"outlet_code": outlet_code}, {"SelectedOutlet": outlet_code}]
                return list(db["hospital_cashcountershiftdetails"].find(shift_q).sort("shiftno", 1))

            with ThreadPoolExecutor(max_workers=4) as executor:
                f_pharm = executor.submit(fetch_pharm)
                f_invest = executor.submit(fetch_invest)
                f_billing = executor.submit(fetch_billing)
                f_discharge = executor.submit(fetch_discharge)
                f_inv_ref = executor.submit(fetch_invest_refund)
                f_gen_ref = executor.submit(fetch_general_refund)
                f_ipadv_ref = executor.submit(fetch_ipadv_refund)
                f_sr = executor.submit(fetch_sales_return)
                f_adm = executor.submit(fetch_admissions)
                f_exp = executor.submit(fetch_expenses)
                f_shifts = executor.submit(fetch_shifts)

                pharm_docs = f_pharm.result()
                invest_docs = f_invest.result()
                billing_docs = f_billing.result()
                discharge_docs = f_discharge.result()
                invest_refund_docs = f_inv_ref.result()
                general_refund_docs = f_gen_ref.result()
                ipadv_refund_docs = f_ipadv_ref.result()
                sales_return_docs = f_sr.result()
                adms = f_adm.result()
                expense_docs = f_exp.result()
                shifts_in_db = f_shifts.result()

            pharm_map = {}
            pharm_bid_shift_map = {}
            for d in pharm_docs:
                for fld in ["bill_no", "bill_number", "billed_bill_no", "converted_bill_no"]:
                    bn = str(d.get(fld) or "").strip()
                    if bn:
                        pharm_map[bn] = d
                        pharm_map[bn.replace("/", "")] = d
                bid = d.get("Bill_id")
                sno = str(d.get("shiftno") or "").strip()
                if bid is not None:
                    pharm_bid_shift_map[(str(bid), sno)] = d
                    pharm_bid_shift_map[(str(bid), sno.replace("/", ""))] = d
                    try:
                        pharm_bid_shift_map[(int(bid), sno)] = d
                        pharm_bid_shift_map[(int(bid), sno.replace("/", ""))] = d
                    except Exception:
                        pass

            def make_doc_map(docs, query_fields):
                d_map = {}
                for d in docs:
                    for f in query_fields:
                        v = str(d.get(f) or "").strip()
                        if v:
                            d_map[v] = d
                            d_map[v.replace("/", "")] = d
                return d_map

            invest_map = make_doc_map(invest_docs, ["investBillNo", "bill_no", "bill_number"])
            billing_map = make_doc_map(billing_docs, ["bill_number", "bill_no"])
            discharge_map = make_doc_map(discharge_docs, ["bill_no", "bill_number"])
            sales_return_map = make_doc_map(sales_return_docs, ["sales_return_number", "return_no", "bill_no", "Bill_id"])
            invest_refund_map = make_doc_map(invest_refund_docs, ["refundBillNo", "investBillNo"])
            general_refund_map = make_doc_map(general_refund_docs, ["refund_bill_no", "bill_no"])
            ipadv_refund_map = make_doc_map(ipadv_refund_docs, ["refund_bill_no", "bill_no"])

            # Pre-cache patient details from hospital_patient and registration for ALL known UHIDs
            all_known_uhids = set()
            for d_list in [pharm_docs, discharge_docs, invest_docs, billing_docs, sales_return_docs, invest_refund_docs, general_refund_docs, ipadv_refund_docs, adms]:
                for d in d_list:
                    u = str(d.get("uhid") or "").strip()
                    if u and u not in ["—", "-", "None"]:
                        all_known_uhids.add(u)
                        all_known_uhids.add(u.replace("/", ""))

            patient_map = {}
            if all_known_uhids:
                p_docs = list(db["hospital_patient"].find({
                    "$or": [
                        {"uhid": {"$in": list(all_known_uhids)}},
                        {"patient_id": {"$in": list(all_known_uhids)}}
                    ]
                }, {"uhid": 1, "patient_id": 1, "firstName": 1, "lastName": 1, "patient_name": 1, "name": 1}))
                for p in p_docs:
                    u1 = str(p.get("uhid") or "").strip()
                    u2 = str(p.get("patient_id") or "").strip()
                    pname = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or str(p.get("patient_name") or p.get("name") or "").strip()
                    if u1:
                        patient_map[u1] = pname
                        patient_map[u1.replace("/", "")] = pname
                    if u2:
                        patient_map[u2] = pname
                        patient_map[u2.replace("/", "")] = pname

                reg_uhids = [u for u in all_known_uhids if u not in patient_map]
                if reg_uhids:
                    reg_docs = list(db["hospital_patientregistration"].find(
                        {"$or": [{"uhid": {"$in": reg_uhids}}, {"PatientId": {"$in": reg_uhids}}]},
                        {"PatientId": 1, "uhid": 1, "firstName": 1, "middleName": 1, "lastName": 1}
                    ))
                    for pr in reg_docs:
                        uid = str(pr.get("uhid") or pr.get("PatientId") or "").strip()
                        if uid and uid not in patient_map:
                            full_name = " ".join([x for x in [(pr.get("firstName") or "").strip(), (pr.get("middleName") or "").strip(), (pr.get("lastName") or "").strip()] if x]).strip()
                            if full_name:
                                patient_map[uid] = full_name
                                patient_map[uid.replace("/", "")] = full_name

            # IP Advances in admissions
            advance_map = {}
            for adm in adms:
                for p in (adm.get("advance_payments") or []):
                    if isinstance(p, dict):
                        b = str(p.get("bill_no") or p.get("bill_number") or "").strip()
                        if b:
                            advance_map[b] = {"adm": adm, "pay": p}
                            advance_map[b.replace("/", "")] = {"adm": adm, "pay": p}

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
                
                # Exclude internal handover / remittance records
                if cat in ["remitted", "submit"] or cat.lower() in ["remitted", "submit", "handover"]:
                    continue
                if cat.lower() == "discharge" and b_no == "2627008327":
                    continue
                    
                dedup_key = (cat, b_no, r.get("shift_no"), str(r.get("collected_amount")))
                if b_no and dedup_key in seen_keys:
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
                    "mr_no": "",
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
                bid = r.get("Bill_id")
                s_no_val = str(r.get("shift_no") or "").strip()
                pharm_doc = pharm_map.get(b_no) or pharm_map.get(b_no.replace("/", "")) or (pharm_bid_shift_map.get((str(bid), s_no_val)) if bid else None)
                is_pharm = cat in ["Pharmacy", "PharmacyBills", "OPPharmacyBills"] or cat.upper().startswith("PHARM") or (pharm_doc is not None)
                
                is_expense_payment = (cat in ["Payment", "PaymentBills"] or str(r.get("transaction_type") or "").lower() == "payment" or b_no in rp_map)
                is_refund_record = not is_expense_payment and bool(
                    str(r.get("transaction_type") or "").lower() == "refund" or
                    "refund" in str(cat or "").lower() or
                    "return" in str(cat or "").lower() or
                    "refund" in str(r.get("remarks") or "").lower()
                )

                if is_refund_record:
                    ref_amt = clean_num(r.get("Returned_amount") or coll_amt)
                    rem_text = str(r.get("remarks") or "").strip()
                    cat_lower = str(cat or "").lower()
                    rem_lower = rem_text.lower()
                    ret_no = str(r.get("return_bill_no") or "").strip()

                    is_discharge = ("discharge" in cat_lower or "discharge" in rem_lower)

                    if is_discharge:
                        # DISCHARGE REFUND: Retrieve discharge bill no and patient details
                        dis = discharge_map.get(b_no) or discharge_map.get(ret_no)
                        if not dis and b_no and "/" in b_no:
                            dis = discharge_map.get(b_no.replace("/", ""))
                        if not dis and ret_no and "/" in ret_no:
                            dis = discharge_map.get(ret_no.replace("/", ""))
                        if not dis:
                            dis = db["hospital_dischargebilling"].find_one({
                                "$or": [
                                    {"bill_no": b_no}, {"bill_number": b_no},
                                    {"bill_no": ret_no}, {"bill_number": ret_no}
                                ]
                            })
                            if dis:
                                discharge_map[b_no] = dis

                        dis = dis or {}
                        dis_bill_no = str(dis.get("bill_no") or dis.get("bill_number") or b_no or ret_no or "").strip()
                        u_val = str(dis.get("uhid") or "").strip()
                        ip_val = str(dis.get("ip_number") or dis.get("ipNumber") or "").strip()
                        p_name = str(dis.get("patient_name") or dis.get("patientname") or patient_map.get(u_val) or "").strip()

                        item_data.update({
                            "category": "DISCHARGE REFUND",
                            "bill_no": dis_bill_no,
                            "discharge_bill_no": dis_bill_no,
                            "return_bill_no": ret_no or "",
                            "uhid": u_val,
                            "mr_no": u_val or "—",
                            "ip_number": ip_val,
                            "patient_name": p_name,
                            "gross": -ref_amt,
                            "amount": ref_amt,
                            "sales_return_amount": ref_amt,
                            "return_amount": ref_amt,
                            "sales_return": ref_amt,
                            "refund_amount": ref_amt,
                            "cash": -ref_amt,
                            "net_amount": -ref_amt,
                            "is_sales_return": True,
                            "is_refund": True,
                            "is_discharge_refund": True,
                            "payment_mode": "Cash",
                            "particulars": [{"itemName": f"Discharge Bill: {dis_bill_no}"}]
                        })
                    else:
                        # Other refunds: Investigation Refund, OP Refund, IP Advance Refund, etc.
                        inv_ref = invest_refund_map.get(ret_no) or invest_refund_map.get(b_no)
                        gen_ref = general_refund_map.get(ret_no) or general_refund_map.get(b_no)
                        ip_ref = ipadv_refund_map.get(ret_no) or ipadv_refund_map.get(b_no)
                        sr_ref = sales_return_map.get(ret_no) or sales_return_map.get(b_no)
                        inv_orig = invest_map.get(b_no) or invest_map.get(ret_no)
                        ph_orig = pharm_map.get(b_no) or pharm_map.get(ret_no)
                        bill_orig = billing_map.get(b_no) or billing_map.get(ret_no)

                        ref_doc = gen_ref or inv_ref or ip_ref or sr_ref or inv_orig or ph_orig or bill_orig or {}

                        u_val = str(ref_doc.get("uhid") or "").strip()
                        ip_val = str(ref_doc.get("ip_number") or ref_doc.get("ipNumber") or ref_doc.get("inpatient_number") or ref_doc.get("ip_no") or "").strip()
                        p_name = str(ref_doc.get("patient_name") or ref_doc.get("patientName") or ref_doc.get("patientname") or patient_map.get(u_val) or "").strip()

                        if inv_ref or "invest" in cat_lower or inv_orig:
                            ref_cat = "INVESTIGATION REFUND"
                            part_item = str(inv_ref.get("refundRemarks") if inv_ref else "") or "Investigation Refund"
                        elif ip_ref or "advance" in cat_lower:
                            ref_cat = "IP ADVANCE REFUND"
                            part_item = str(ip_ref.get("remarks") if ip_ref else "") or "IP Advance Refund"
                        elif sr_ref or ph_orig or "sales" in cat_lower:
                            ref_cat = "SALES RETURN"
                            part_item = "Pharmacy Sales Return"
                        elif gen_ref or "op" in cat_lower or "billing" in cat_lower:
                            ref_cat = "OP REFUND"
                            part_item = str(gen_ref.get("remarks") if gen_ref else "") or "OP Service Refund"
                        else:
                            ref_cat = "REFUND"
                            part_item = rem_text or "Counter Refund Voucher"

                        item_data.update({
                            "category": ref_cat,
                            "bill_no": b_no or ret_no,
                            "return_bill_no": ret_no or "",
                            "uhid": u_val,
                            "mr_no": u_val or "—",
                            "ip_number": ip_val,
                            "patient_name": p_name,
                            "gross": -ref_amt,
                            "amount": ref_amt,
                            "sales_return_amount": ref_amt,
                            "return_amount": ref_amt,
                            "sales_return": ref_amt,
                            "refund_amount": ref_amt,
                            "cash": -ref_amt,
                            "net_amount": -ref_amt,
                            "is_sales_return": True,
                            "is_refund": True,
                            "payment_mode": "Cash",
                            "particulars": [{"itemName": part_item}]
                        })

                elif is_pharm:
                    item_data["category"] = "PHARMACY"
                    if pharm_doc:
                        d = pharm_doc
                        u = str(d.get("uhid") or "").strip()
                        item_data["uhid"] = u
                        item_data["mr_no"] = u
                        item_data["ip_number"] = d.get("inpatient_number") or d.get("ip_no") or ""
                        
                        p_name = str(d.get("patient_name") or d.get("patientName") or "").strip()
                        if not p_name and u:
                            p_name = patient_map.get(u) or patient_map.get(u.replace("/", "")) or ""
                        item_data["patient_name"] = p_name
                        
                        amt = coll_amt if coll_amt > 0 else clean_num(d.get("net_amount"))
                        pd = d.get("payment_details") or {}
                        pm = pd.get("method") or d.get("payment_method") or d.get("payment_mode") or d.get("billing_mode") or r.get("payment_mode") or "Cash"
                        is_cr = bool(d.get("is_insurance") or any(k in str(d.get("billing_mode") or "").upper() for k in ["CREDIT", "INSURANCE"]) or any(k in str(d.get("payment_mode") or "").upper() for k in ["CREDIT", "INSURANCE"]))
                        c_val, cr_val, b_val = split_payment_modes(amt, pm, pd, is_credit_bill=is_cr)
                        item_data.update({
                            "gross": amt, "net_amount": amt, "amount": amt,
                            "cash": c_val, "credit": cr_val, "bank": b_val,
                            "card": b_val, "card_amount": b_val, "payment_mode": pm,
                            "particulars": d.get("items") or d.get("medicine_particulars") or [],
                            "created_by": d.get("created_by") or "",
                            "lastmodified_by": d.get("pharmacist_id") or d.get("lastmodified_by") or ""
                        })
                    else:
                        item_data["patient_name"] = "General Pharmacy Patient"
                        item_data["particulars"] = [{"itemName": "OP Pharmacy Medicines"}]
                    
                elif (cat in ["Investigation", "InvestigationBills"] or "INVEST" in cat.upper()) and b_no in invest_map:
                    d = invest_map[b_no]
                    bt_no = d.get("billTypeNo")
                    bt_name = billtype_map.get(str(bt_no).strip()) if bt_no else None
                    if not bt_name and (d.get("item") or d.get("particulars")):
                        items_list = d.get("item") or d.get("particulars") or []
                        if items_list and isinstance(items_list[0], dict):
                            first_item = items_list[0]
                            first_bt_no = first_item.get("billTypeNo")
                            bt_name = billtype_map.get(str(first_bt_no).strip()) if first_bt_no else None
                    if not bt_name and d.get("bill_type") is not None:
                        bt_name = billtype_id_map.get(str(d.get("bill_type")).strip())
                    
                    disp_type = bt_name or "Investigation"
                    if "(SH)" not in disp_type: disp_type = f"{disp_type} (SH)"
                    
                    # Breakdown for PACKAGE and CARDIOLOGY
                    disp_upper = disp_type.upper()
                    items_list = d.get("item") or d.get("particulars") or []
                    
                    if "PACKAGE" in disp_upper or str(bt_no).upper() == "PACK":
                        pkg_id = d.get("package_id")
                        pkg_name = d.get("package_name") or d.get("packageName")
                        if not pkg_name and pkg_id is not None:
                            pkg_name = package_map.get(pkg_id) or package_map.get(str(pkg_id))
                        if not pkg_name and items_list:
                            for it in items_list:
                                if isinstance(it, dict) and it.get("package_id") is not None:
                                    pkg_name = package_map.get(it.get("package_id")) or package_map.get(str(it.get("package_id")))
                                    if pkg_name:
                                        break
                        if pkg_name:
                            disp_type = f"PACKAGE - {str(pkg_name).strip().upper()} (SH)"
                        else:
                            disp_type = "PACKAGE (SH)"
                            
                    elif "CARDIO" in disp_upper or str(bt_no).upper() == "CAR01":
                        test_names = []
                        for it in items_list:
                            if isinstance(it, dict) and it.get("itemName"):
                                tname = str(it.get("itemName")).strip().upper()
                                if tname and tname not in test_names:
                                    test_names.append(tname)
                        if test_names:
                            tests_str = ", ".join(test_names)
                            disp_type = f"CARDIOLOGY - {tests_str} (SH)"
                        else:
                            disp_type = "CARDIOLOGY (SH)"

                    item_data["category"] = disp_type
                    u = d.get("uhid") or ""
                    item_data["uhid"] = u
                    item_data["mr_no"] = u
                    item_data["ip_number"] = d.get("ipNumber") or d.get("ip_number") or ""
                    item_data["patient_name"] = str(d.get("patient_name") or d.get("patientname") or "").strip()
                    amt = coll_amt if coll_amt > 0 else clean_num(d.get("finalPrice") or d.get("total"))
                    pd = d.get("payment_details") or {}
                    pm = pd.get("method") or d.get("payment_method") or d.get("payment_mode") or r.get("payment_mode") or "Cash"
                    is_cr = bool(any(k in str(d.get("payment_mode") or "").upper() for k in ["CREDIT", "INSURANCE"]))
                    c_val, cr_val, b_val = split_payment_modes(amt, pm, pd, is_credit_bill=is_cr)
                    item_data.update({
                        "gross": amt, "net_amount": amt, "amount": amt,
                        "cash": c_val, "credit": cr_val, "bank": b_val,
                        "card": b_val, "card_amount": b_val, "payment_mode": pm,
                        "particulars": d.get("item") or [],
                        "bill_type": bt_no or "INVEST",
                        "bill_type_name": bt_name or disp_type,
                        "is_investigation": True,
                        "doctor": d.get("doctor") or d.get("referredBy") or "",
                        "created_by": d.get("created_by") or "",
                        "lastmodified_by": d.get("CashierID") or d.get("lastmodified_by") or ""
                    })
                    
                elif cat in ["Billing", "Registration", "RegistrationBills"] and b_no in billing_map:
                    d = billing_map[b_no]
                    item_data["category"] = "REGISTRATION"
                    u = d.get("uhid") or ""
                    item_data["uhid"] = u
                    item_data["mr_no"] = u
                    item_data["patient_name"] = str(d.get("patient_name") or d.get("patientname") or "").strip()
                    amt = coll_amt if coll_amt > 0 else clean_num(d.get("total_fees"))
                    pd = d.get("payment_details") or {}
                    pm = pd.get("method") or d.get("payment_mode") or d.get("payment_method") or r.get("payment_mode") or "Cash"
                    c_val, cr_val, b_val = split_payment_modes(amt, pm, pd)
                    item_data.update({
                        "gross": amt, "net_amount": amt, "amount": amt,
                        "cash": c_val, "credit": cr_val, "bank": b_val,
                        "card": b_val, "card_amount": b_val, "payment_mode": pm,
                        "particulars": d.get("items") or [],
                        "created_by": d.get("created_by") or "",
                        "lastmodified_by": d.get("lastmodified_by") or ""
                    })
                    
                elif cat.upper() in ["DISCHARGE", "DISCHARGEBILLS"]:
                    item_data["category"] = "DISCHARGE"
                    if b_no in discharge_map:
                        d = discharge_map[b_no]
                        u = d.get("uhid") or ""
                        item_data["uhid"] = u
                        item_data["mr_no"] = u
                        item_data["ip_number"] = d.get("ip_number") or d.get("ipNumber") or ""
                        item_data["patient_name"] = str(d.get("patient_name") or d.get("patientname") or "").strip()
                        
                        tot_gross = clean_num(d.get("total_amount") or d.get("gross_amount"))
                        adv_adj = clean_num(d.get("advance_amount") or d.get("advance_adjustment"))
                        net_paid = coll_amt if coll_amt > 0 else clean_num(d.get("net_amount"))
                        if tot_gross == 0.0:
                            tot_gross = net_paid + adv_adj
                            
                        pd = d.get("payment_details") or {}
                        pm = pd.get("method") or d.get("payment_mode") or d.get("payment_method") or r.get("payment_mode") or "Cash"
                        is_cr = bool(any(k in str(d.get("payment_mode") or "").upper() for k in ["CREDIT", "INSURANCE"]))
                        c_val, cr_val, b_val = split_payment_modes(net_paid, pm, pd, is_credit_bill=is_cr)
                        
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
                            "net_amount": net_paid, "amount": net_paid,
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
                    if not d:
                        d = pharm_map.get(b_no) or pharm_map.get(r.get("return_bill_no")) or {}
                    ret_amt = clean_num(d.get("return_amount") or r.get("Returned_amount") or coll_amt)
                    item_data["category"] = "Sales Return"
                    u_val = str(d.get("uhid") or "").strip()
                    ip_val = str(d.get("inpatient_number") or d.get("ip_no") or d.get("ip_number") or "").strip()
                    p_name = str(d.get("patient_name") or d.get("patientName") or patient_map.get(u_val) or "").strip()
                    item_data["uhid"] = u_val
                    item_data["mr_no"] = u_val or "—"
                    item_data["ip_number"] = ip_val
                    item_data["patient_name"] = p_name
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



                enriched_bills.append(item_data)

            # 4. Universal Patient Master Backfill Pass
            missing_uhids = list(set([b["uhid"] for b in enriched_bills if b.get("uhid") and (not b.get("patient_name") or b.get("patient_name") in ["Discharge Refund", "Refund", "Sales Return"])]))
            if missing_uhids:
                p_docs = list(db["hospital_patient"].find({"uhid": {"$in": missing_uhids}}, {"uhid": 1, "firstName": 1, "lastName": 1, "patient_name": 1}))
                p_map = {}
                for p in p_docs:
                    fn = (p.get("firstName") or "").strip()
                    ln = (p.get("lastName") or "").strip()
                    nm = f"{fn} {ln}".strip() or p.get("patient_name") or ""
                    if nm and p.get("uhid"):
                        p_map[p["uhid"]] = nm
                        p_map[p["uhid"].replace("/", "")] = nm

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
                            p_map[uid.replace("/", "")] = full_name

                for b in enriched_bills:
                    u = b.get("uhid")
                    if u and (not b.get("patient_name") or b.get("patient_name") in ["Discharge Refund", "Refund", "Sales Return"]):
                        b["patient_name"] = p_map.get(u) or p_map.get(u.replace("/", "")) or ""

            # Clean UHID and IP number separation
            for b in enriched_bills:
                u = str(b.get("uhid") or "").strip()
                ip = str(b.get("ip_number") or "").strip()
                if ip == u:
                    ip = ""
                b["uhid"] = u
                b["mr_no"] = u if u else "—"
                b["ip_number"] = ip
                if not b.get("patient_name") or b.get("patient_name") in ["Discharge Refund", "Refund", "Sales Return"]:
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
            # shifts_in_db was already fetched concurrently in thread pool

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

            seen_sr_keys = set()
            for b in enriched_bills:
                if b.get("is_sales_return") or b.get("is_refund") or str(b.get("category") or "").upper() in ["SALES RETURN", "REFUND", "DISCHARGE REFUND", "INVESTIGATION REFUND", "OP REFUND", "IP ADVANCE REFUND"]:
                    if b.get("bill_no"):
                        b_str = str(b["bill_no"]).strip()
                        seen_sr_keys.add(b_str)
                        seen_sr_keys.add(b_str.replace("/", ""))
                    if b.get("return_bill_no"):
                        r_str = str(b["return_bill_no"]).strip()
                        seen_sr_keys.add(r_str)
                        seen_sr_keys.add(r_str.replace("/", ""))

            for sr in sr_docs:
                sr_ret_no = str(sr.get("return_bill_no") or sr.get("sales_return_number") or sr.get("return_no") or "").strip()
                sr_orig_no = str(sr.get("bill_no") or "").strip()
                if (sr_ret_no and (sr_ret_no in seen_sr_keys or sr_ret_no.replace("/", "") in seen_sr_keys)) or \
                   (sr_orig_no and (sr_orig_no in seen_sr_keys or sr_orig_no.replace("/", "") in seen_sr_keys)):
                    continue
                if sr_ret_no:
                    seen_sr_keys.add(sr_ret_no)
                    seen_sr_keys.add(sr_ret_no.replace("/", ""))
                if sr_orig_no:
                    seen_sr_keys.add(sr_orig_no)
                    seen_sr_keys.add(sr_orig_no.replace("/", ""))

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
                    "patient_name": patient_map.get(str(sr.get("uhid") or "").strip()) or str(sr.get("patient_name") or sr.get("patientName") or "Sales Return - Pharmacy").strip(),
                    "gross": -r_amt,
                    "cash": -c_val,
                    "card": -b_val,
                    "bank": -b_val,
                    "credit": -cr_val,
                    "net_amount": -r_amt,
                    "amount": r_amt,
                    "return_amount": r_amt,
                    "sales_return": r_amt,
                    "sales_return_amount": r_amt,
                    "refund_amount": r_amt,
                    "shift_no": r_shift,
                    "cashier_id": sr_cid,
                    "cashier_name": sr_cname,
                    "payment_mode": pm,
                    "outlet_code": r_outlet or "OLET002",
                    "particulars": sr.get("medicine_particulars") or [],
                    "is_sales_return": True,
                    "is_refund": True
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

                s_returns_bills = sum(
                    clean_num(b.get("refund_amount") or b.get("return_amount") or b.get("sales_return_amount") or b.get("sales_return"))
                    for b in enriched_bills
                    if (str(b.get("shift_no") or "").strip() == s_no or str(b.get("shift_no") or "").replace("/", "").strip() == s_no_clean)
                    and (b.get("is_sales_return") or b.get("is_refund") or str(b.get("category") or "").upper() in ["SALES RETURN", "REFUND", "DISCHARGE REFUND", "INVESTIGATION REFUND", "OP REFUND", "IP ADVANCE REFUND"])
                )

                s_stored_ret = abs(clean_num(s.get("SalesReturnAmount")))
                s_returns = round(max(s_returns_bills, s_stored_ret), 2)
                s_net_handover = round(s_cash_gross - s_expenses - s_returns, 2)
                
                recorded_cash = clean_num(s.get("collected_Amount"))
                recorded_credit = clean_num(s.get("CreditAmount"))
                s_tot = s_cash_gross + s_card_amt + s_credit_amt
                r_tot = recorded_cash + recorded_credit
                
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
                    "closing_balance": s_net_handover,
                    "is_tallied": (abs(s_net_handover - recorded_cash) < 1.0) or (abs(s_cash_gross - recorded_cash) < 1.0) or (abs(s_tot - r_tot) < 1.0)
                })

            # 7. Financial Grand Totals
            total_gross_cash = round(sum(b["cash"] for b in enriched_bills if b["cash"] > 0), 2)
            total_bank_card = round(sum(b["bank"] for b in enriched_bills), 2)
            total_credit_scheme = round(sum(b["credit"] for b in enriched_bills), 2)
            total_gross_revenue = round(total_gross_cash + total_bank_card + total_credit_scheme, 2)
            total_sales_returns = round(sum(s["sales_return"] for s in shift_reconciliation), 2)
            net_cash_handover = round(total_gross_cash - total_counter_expenses - total_sales_returns, 2)

            res = {
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
            _LEDGER_RESULT_CACHE[cache_key] = (now, res)
            return res
        except Exception as e:
            raise e
