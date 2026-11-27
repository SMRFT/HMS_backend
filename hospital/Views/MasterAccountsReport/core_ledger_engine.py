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

def _to_naive_dt(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None)
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    if isinstance(val, str):
        s = val.strip()
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %I:%M %p",
            "%d/%m/%Y",
            "%d-%m-%Y",
        ):
            try:
                return datetime.strptime(s[:19], fmt)
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

def extract_card_metadata(pd, pm_str="", b_val=0.0):
    if isinstance(pd, str):
        try:
            pd = _json.loads(pd)
        except Exception:
            pd = {}
    if not isinstance(pd, dict):
        pd = {}
    pm_upper = str(pm_str or "").strip().upper()

    # Search for card / digital breakdown item if present
    breakdown_item = None
    breakdown = pd.get("breakdown")
    if isinstance(breakdown, list):
        for item in breakdown:
            if isinstance(item, dict):
                m_str = str(item.get("method") or item.get("payment_mode") or "").strip().lower()
                if (
                    any(k in m_str for k in ["card", "bank", "pos", "upi", "paytm", "online", "cheque", "neft", "gpay", "phonepe"]) or
                    item.get("Card Machine") or item.get("card_machine") or item.get("cardMachine") or item.get("pos_machine") or
                    (m_str != "cash" and float(item.get("Paid_amount") or item.get("amount") or 0) > 0)
                ):
                    breakdown_item = item
                    break

    def _get_val(*keys):
        for k in keys:
            v = pd.get(k)
            if v and str(v).strip():
                return str(v).strip()
        if breakdown_item:
            for k in keys:
                v = breakdown_item.get(k)
                if v and str(v).strip():
                    return str(v).strip()
        return ""

    # 1. Card Machine / Terminal
    c_mach = _get_val(
        "Card Machine", "card_machine", "cardMachine", "pos_machine",
        "machine_name", "machine", "pos", "terminal", "terminal_machine", "card_name"
    )

    combined_pm = pm_upper
    if breakdown_item:
        b_m = str(breakdown_item.get("method") or breakdown_item.get("payment_mode") or "").strip().upper()
        if b_m:
            combined_pm = f"{combined_pm} {b_m}"

    if not c_mach:
        if "PAYTM" in combined_pm: c_mach = "Paytm"
        elif "BAJAJ" in combined_pm: c_mach = "Bajaj"
        elif "360" in combined_pm: c_mach = "360 POS"
        elif "PNB" in combined_pm: c_mach = "PNB"
        elif "HDFC" in combined_pm: c_mach = "HDFC POS"
        elif "SBI" in combined_pm: c_mach = "SBI POS"
        elif "PINE" in combined_pm: c_mach = "PINELABS"
        elif any(k in combined_pm for k in ["UPI", "GPAY", "GOOGLE", "PHONEPE", "BHIM", "QR"]): c_mach = "UPI"
        elif b_val > 0: c_mach = "POS"
        else: c_mach = ""
    else:
        c_mach = str(c_mach).strip()

    # 2. Card Type
    c_type = _get_val("card_type", "cardType")
    if not c_type and breakdown_item:
        b_m = str(breakdown_item.get("method") or "").strip().upper()
        if b_m and b_m not in ["CASH", "MULTIPLE PAYMENT", "MULTIPLE"]:
            if any(k in b_m for k in ["UPI", "GPAY", "GOOGLE", "PHONEPE", "BHIM", "QR"]):
                c_type = "UPI"
            elif "CARD" in b_m:
                c_type = b_m
            else:
                c_type = "CARD"
    if not c_type:
        if any(k in combined_pm for k in ["UPI", "GPAY", "GOOGLE", "PHONEPE", "BHIM", "QR"]) or c_mach == "UPI":
            c_type = "UPI"
        elif "RUPAY" in combined_pm: c_type = "RUPAY CARD"
        elif "VISA" in combined_pm: c_type = "VISA CARD"
        elif "MASTER" in combined_pm: c_type = "MASTER CARD"
        elif "AMEX" in combined_pm or "AMERICAN" in combined_pm: c_type = "AMEX CARD"
        elif "DEBIT" in combined_pm: c_type = "DEBIT CARD"
        elif "CREDIT" in combined_pm: c_type = "CREDIT CARD"
        elif b_val > 0: c_type = "CARD"
        else: c_type = ""
    else:
        c_type = str(c_type).strip().upper()

    # 3. Card Number
    c_num = _get_val("card_number", "cardNumber", "card_no")

    return c_mach, c_type, str(c_num).strip()

def extract_misc_details(r, ep=None):
    """
    Extracts party/patient name, room number, description/narration, and account head
    giving priority to hospital_cashcountercollection first, then falling back to hospital_receiptandpayment.
    """
    p_name = ""
    r_no = ""
    desc = ""
    ac_head = ""

    # 1. First from hospital_cashcountercollection (r)
    raw_rem = r.get("remarks") if isinstance(r, dict) else None
    if raw_rem:
        if isinstance(raw_rem, str) and raw_rem.strip().startswith("{") and raw_rem.strip().endswith("}"):
            try:
                import json
                pj = json.loads(raw_rem)
                p_name = str(pj.get("patient_name") or pj.get("name") or pj.get("party_name") or "").strip()
                r_no = str(pj.get("room_no") or pj.get("room") or "").strip()
                desc = str(pj.get("description") or pj.get("narration") or pj.get("reason") or "").strip()
            except Exception:
                desc = str(raw_rem).strip()
        elif isinstance(raw_rem, dict):
            p_name = str(raw_rem.get("patient_name") or raw_rem.get("name") or raw_rem.get("party_name") or "").strip()
            r_no = str(raw_rem.get("room_no") or raw_rem.get("room") or "").strip()
            desc = str(raw_rem.get("description") or raw_rem.get("narration") or raw_rem.get("reason") or "").strip()
        else:
            desc = str(raw_rem).strip()

    # 2. Fallback to hospital_receiptandpayment (ep)
    if ep and isinstance(ep, dict):
        ac_head = str(ep.get("account_head") or "").strip()
        ep_desc = ep.get("description")
        if ep_desc:
            if isinstance(ep_desc, str) and ep_desc.strip().startswith("{") and ep_desc.strip().endswith("}"):
                try:
                    import json
                    pj2 = json.loads(ep_desc)
                    if not p_name:
                        p_name = str(pj2.get("patient_name") or pj2.get("name") or pj2.get("party_name") or "").strip()
                    if not r_no:
                        r_no = str(pj2.get("room_no") or pj2.get("room") or "").strip()
                    if not desc:
                        desc = str(pj2.get("description") or pj2.get("narration") or pj2.get("reason") or "").strip()
                except Exception:
                    if not desc:
                        desc = str(ep_desc).strip()
            elif isinstance(ep_desc, dict):
                if not p_name:
                    p_name = str(ep_desc.get("patient_name") or ep_desc.get("name") or ep_desc.get("party_name") or "").strip()
                if not r_no:
                    r_no = str(ep_desc.get("room_no") or ep_desc.get("room") or "").strip()
                if not desc:
                    desc = str(ep_desc.get("description") or ep_desc.get("narration") or ep_desc.get("reason") or "").strip()
            else:
                if not desc:
                    desc = str(ep_desc).strip()

        if not p_name:
            p_name = str(ep.get("paid_to_or_received_from") or "").strip()
            if p_name == "-":
                p_name = ""

    # Build clean display strings
    if p_name and r_no:
        room_label = r_no if r_no.lower().startswith("room") else f"Room {r_no}"
        display_name = f"{p_name} ({room_label})"
        item_particular = room_label
    elif p_name:
        display_name = p_name
        item_particular = desc or ac_head or "Miscellaneous"
    elif desc and r_no:
        room_label = r_no if r_no.lower().startswith("room") else f"Room {r_no}"
        display_name = f"{desc} ({room_label})"
        item_particular = room_label
    elif desc:
        display_name = desc
        item_particular = desc
    elif ac_head:
        display_name = ac_head
        item_particular = ac_head
    else:
        display_name = "Sundry / Miscellaneous"
        item_particular = "Miscellaneous Receipt"

    return display_name, item_particular, p_name, r_no, desc, ac_head

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
                "return_bill_no": 1, "Returned_amount": 1,
                "uhid": 1, "ip_number": 1, "card_amount": 1, "bank_amount": 1,
                "cash_amount": 1, "cheque_amount": 1, "credit_amount": 1,
                "payment_details": 1, "bill_type": 1
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
                rp_q = {"$or": [
                    {"created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
                    {"voucher_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}}
                ]}
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
            for d_list in [ccc_records, pharm_docs, discharge_docs, invest_docs, billing_docs, sales_return_docs, invest_refund_docs, general_refund_docs, ipadv_refund_docs, adms]:
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
                    try:
                        rp_map[str(int(v_no))] = ep
                    except Exception:
                        pass
                    if len(v_no) < 8 and v_no.isdigit():
                        rp_map[v_no.zfill(8)] = ep

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
                
                # Module-specific identification
                bid = r.get("Bill_id")
                s_no_val = str(r.get("shift_no") or "").strip()
                cat_str = str(cat or "").strip()
                cat_lower = cat_str.lower()
                trans_lower = str(r.get("transaction_type") or "").lower()
                b_type = r.get("bill_type")

                is_misc = (
                    cat_str in ["Receipt", "Payment", "Miscellaneous", "Misc", "Sundry", "Counter Payment", "Counter Receipt", "ReceiptBills", "PaymentBills"] or
                    cat_lower in ["receipt", "payment", "miscellaneous", "misc", "sundry"] or
                    trans_lower in ["payment", "receipt"] or
                    b_no in rp_map
                ) and not (
                    "advance" in cat_lower or
                    "discharge" in cat_lower or
                    "registration" in cat_lower or
                    "pharm" in cat_lower or
                    "invest" in cat_lower
                )
                is_expense_payment = (
                    cat_str in ["Payment", "PaymentBills"] or
                    trans_lower == "payment" or
                    (b_no in rp_map and str(rp_map[b_no].get("receipt_type") or "").lower() == "payment")
                ) and not (
                    "advance" in cat_lower or
                    "discharge" in cat_lower or
                    "registration" in cat_lower
                )
                is_explicit_advance = (
                    cat_str in ["IPAdvance", "IPAdvanceBills", "IPAdvance Payment", "Advance", "advance"] or
                    ("advance" in cat_lower) or
                    ("advance" in trans_lower and not is_misc) or
                    (b_type == 1 and not is_misc and "receipt" not in cat_lower and "payment" not in cat_lower)
                ) and not is_misc
                is_refund_record = not is_expense_payment and not is_misc and bool(
                    trans_lower == "refund" or
                    "refund" in cat_lower or
                    "return" in cat_lower or
                    "refund" in str(r.get("remarks") or "").lower()
                )
                is_explicit_registration = (
                    cat_str in ["Registration", "RegistrationBills", "REGISTRATION"] or
                    "registration" in cat_lower or
                    "op registration" in cat_lower or
                    b_type == 0
                ) and not is_explicit_advance and not is_misc
                is_explicit_investigation = (
                    cat_str in ["Investigation", "InvestigationBills"] or
                    "invest" in cat_lower or
                    "scan" in cat_lower or
                    "lab" in cat_lower or
                    "x-ray" in cat_lower or
                    "xray" in cat_lower or
                    "ecg" in cat_lower
                ) and not is_explicit_advance and not is_misc
                is_explicit_discharge = (
                    cat_str.upper() in ["DISCHARGE", "DISCHARGEBILLS"] or
                    "discharge" in cat_lower
                ) and not is_explicit_advance and not is_misc

                # Non-pharmacy records must NEVER be hijacked by slash-stripped pharmacy bill collisions
                is_non_pharm = is_explicit_advance or is_expense_payment or is_refund_record or is_explicit_registration or is_explicit_investigation or is_explicit_discharge or is_misc

                pharm_doc = None
                if not is_non_pharm:
                    pharm_doc = pharm_map.get(b_no) or (pharm_bid_shift_map.get((str(bid), s_no_val)) if bid else None)
                    if not pharm_doc and "/" in b_no:
                        pharm_doc = pharm_map.get(b_no.replace("/", ""))

                is_pharm = not is_non_pharm and (
                    cat_str in ["Pharmacy", "PharmacyBills", "OPPharmacyBills"] or
                    cat_str.upper().startswith("PHARM") or
                    (pharm_doc is not None)
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
                        c_mach, c_type, c_num = extract_card_metadata(pd, pm, b_val)
                        item_data.update({
                            "gross": amt, "net_amount": amt, "amount": amt,
                            "cash": c_val, "credit": cr_val, "bank": b_val,
                            "card": b_val, "card_amount": b_val, "payment_mode": pm,
                            "card_machine": c_mach, "card_type": c_type, "card_number": c_num,
                            "payment_details": pd,
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
                    pkg_name = None
                    is_pkg = False
                    
                    if "PACKAGE" in disp_upper or str(bt_no).upper() == "PACK":
                        is_pkg = True
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
                        # User request: Packages collection under LAB collections
                        lab_category = billtype_map.get("LAB01") or "LAB BILL (CREDIT/TKT/GENERAL)"
                        if "(SH)" not in lab_category:
                            lab_category = f"{lab_category} (SH)"
                        disp_type = lab_category
                            
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
                    c_mach, c_type, c_num = extract_card_metadata(pd, pm, b_val)
                    item_data.update({
                        "gross": amt, "net_amount": amt, "amount": amt,
                        "cash": c_val, "credit": cr_val, "bank": b_val,
                        "card": b_val, "card_amount": b_val, "payment_mode": pm,
                        "card_machine": c_mach, "card_type": c_type, "card_number": c_num,
                        "payment_details": pd,
                        "particulars": d.get("item") or [],
                        "bill_type": bt_no or "INVEST",
                        "bill_type_name": bt_name or disp_type,
                        "is_investigation": True,
                        "package_name": pkg_name or "",
                        "is_package": is_pkg,
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
                    c_mach, c_type, c_num = extract_card_metadata(pd, pm, b_val)
                    item_data.update({
                        "gross": amt, "net_amount": amt, "amount": amt,
                        "cash": c_val, "credit": cr_val, "bank": b_val,
                        "card": b_val, "card_amount": b_val, "payment_mode": pm,
                        "card_machine": c_mach, "card_type": c_type, "card_number": c_num,
                        "payment_details": pd,
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
                        c_mach, c_type, c_num = extract_card_metadata(pd, pm, b_val)
                        
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
                            "card_machine": c_mach, "card_type": c_type, "card_number": c_num,
                            "payment_details": pd,
                            "room_charges": round(room_c, 2), "nursing_charges": round(nursing_c, 2),
                            "doctor_charges": round(doctor_c, 2), "doctor_fees": round(doctor_c, 2),
                            "lab_charges": round(lab_c, 2), "pharmacy_charges": round(pharm_c, 2),
                            "particulars": items
                        })
                    
                elif is_explicit_advance or cat in ["IPAdvance", "IPAdvanceBills", "IPAdvance Payment", "Advance", "advance"] or (b_no in advance_map):
                    adv_info = advance_map.get(b_no) or (advance_map.get(b_no.replace("/", "")) if "/" in b_no else None)
                    item_data["category"] = "ADVANCE"
                    
                    r_uhid = str(r.get("uhid") or "").strip()
                    r_ip = str(r.get("ip_number") or "").strip()
                    r_pm = r.get("payment_mode") or "Cash"
                    r_pd = r.get("payment_details") or {}
                    r_card = clean_num(r.get("card_amount"))
                    r_bank = clean_num(r.get("bank_amount"))
                    r_cash = clean_num(r.get("cash_amount"))
                    r_credit = clean_num(r.get("credit_amount"))

                    if adv_info:
                        adm = adv_info["adm"]
                        pay = adv_info["pay"]
                        u_val = adm.get("uhid") or r_uhid
                        ip_val = adm.get("ipNumber") or r_ip
                        p_name = str(pay.get("patient_name") or adm.get("patient_name") or adm.get("patientname") or patient_map.get(u_val) or "").strip()
                        amt = clean_num(pay.get("advance_amount") or pay.get("amount") or coll_amt)
                        pd = pay.get("payment_details") or r_pd
                        pm = pd.get("method") or pay.get("payment_mode") or r_pm
                    else:
                        u_val = r_uhid
                        ip_val = r_ip
                        p_name = str(patient_map.get(u_val) or patient_map.get(u_val.replace("/", "")) or "").strip()
                        amt = coll_amt
                        pd = r_pd
                        pm = r_pm

                    if r_card > 0 or r_bank > 0 or (r_cash > 0 and r_cash != coll_amt):
                        c_val = r_cash
                        b_val = r_card if r_card > 0 else r_bank
                        # If credit_amount equals card/bank amount, actual insurance/patient credit is 0
                        cr_val = max(0.0, round(r_credit - b_val, 2)) if r_credit >= b_val else r_credit
                    else:
                        c_val, cr_val, b_val = split_payment_modes(amt, pm, pd)

                    c_mach, c_type, c_num = extract_card_metadata(pd, pm, b_val)
                    all_credit_val = round(cr_val + b_val, 2)
                    item_data.update({
                        "uhid": u_val,
                        "mr_no": u_val or "—",
                        "ip_number": ip_val,
                        "patient_name": p_name,
                        "gross": amt, "net_amount": amt, "amount": amt, "advance_amount": amt,
                        "cash": c_val, "credit": cr_val, "bank": b_val,
                        "card": b_val, "card_amount": b_val, "bank_amount": b_val,
                        "cash_amount": c_val, "credit_amount": all_credit_val,
                        "payment_mode": pm,
                        "card_machine": c_mach, "card_type": c_type, "card_number": c_num,
                        "payment_details": pd
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
                        
                elif is_misc:
                    ep = rp_map.get(b_no) or (rp_map.get(str(int(b_no))) if b_no.isdigit() else None)
                    is_pay = is_expense_payment or (ep and str(ep.get("receipt_type") or "").lower() == "payment")

                    display_name, item_particular, pt_n, rm_n, ds_t, ac_head = extract_misc_details(r, ep)

                    if is_pay:
                        pay_amt = clean_num(r.get("Returned_amount") or (ep.get("amount") if ep else 0) or coll_amt)
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
                            "particulars": [{"itemName": item_particular, "account_head": ac_head}]
                        })
                    else:
                        rec_amt = coll_amt if coll_amt > 0 else clean_num(r.get("collected_amount") or (ep.get("amount") if ep else 0))
                        pm = r.get("payment_mode") or (ep.get("payment_mode") if ep else None) or "Cash"
                        pd = r.get("payment_details") or {}

                        r_card = clean_num(r.get("card_amount"))
                        r_bank = clean_num(r.get("bank_amount"))
                        r_cash = clean_num(r.get("cash_amount"))

                        if r_card > 0 or r_bank > 0 or (r_cash > 0 and r_cash != rec_amt):
                            c_val = r_cash
                            b_val = r_card if r_card > 0 else r_bank
                        else:
                            c_val, cr_val, b_val = split_payment_modes(rec_amt, pm, pd)

                        c_mach, c_type, c_num = extract_card_metadata(pd, pm, b_val)

                        item_data.update({
                            "category": "MISCELLANEOUS",
                            "patient_name": display_name,
                            "gross": rec_amt,
                            "amount": rec_amt,
                            "net_amount": rec_amt,
                            "cash": c_val,
                            "bank": b_val,
                            "card": b_val,
                            "card_amount": b_val,
                            "bank_amount": b_val,
                            "cash_amount": c_val,
                            "payment_mode": pm,
                            "card_machine": c_mach,
                            "card_type": c_type,
                            "card_number": c_num,
                            "payment_details": pd,
                            "particulars": [{"itemName": item_particular, "account_head": ac_head}]
                        })



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
                rc_dt_safe = _to_naive_dt(rc_dt)
                if not r_shift and rc_dt_safe:
                    for sh in shifts_in_db:
                        sh_outlet = str(sh.get("SelectedOutlet") or sh.get("outlet_code") or "").strip()
                        if not r_outlet or sh_outlet == r_outlet:
                            sh_start = _to_naive_dt(sh.get("StartingTime"))
                            sh_end = _to_naive_dt(sh.get("closingTime")) or (sh_start + timedelta(hours=14) if sh_start else None)
                            if sh_start and sh_end and (sh_start <= rc_dt_safe <= sh_end):
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
