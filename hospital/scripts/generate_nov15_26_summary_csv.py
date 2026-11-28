"""
Read-only HMS Cash Counter, Shift Tally, Discount & Pending Bills CSV Generator
================================================================================
Period: 2026-11-15 00:00:00 IST to 2026-11-26 23:59:59 IST

Combines:
1. Stored Shift Details (hospital_cashcountershiftdetails)
2. Batched Module Shift Calculation (cashcounter.calculate_shift_collection logic)
3. Enriched Counter Ledger (AccountsLedgerEngine: deduplicated hospital_cashcountercollection
   joined with Pharmacy/Investigation/Registration/Discharge/Advance/Return docs, plus
   Payment-only expenses from hospital_receiptandpayment)
4. Exact Discount Extraction across Pharmacy, Investigation, and Discharge
5. Date-wise & Module-wise Pending Bills across all HMS billing collections

Generates 4 CSV summaries in d:\\Parthi\\HMS\\:
1. HMS_CashCounter_Cash_Credit_Discount_Report_15_to_26_Nov_2026.csv
2. HMS_Brief_Executive_Summary_15_to_26_Nov_2026.csv
3. HMS_Shift_Tally_Summary_15_to_26_Nov_2026.csv
4. HMS_Daily_Pending_Bills_Summary_15_to_26_Nov_2026.csv
"""

import csv
import os
import sys
import json
import ast
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUTPUT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shanmugahospital_backend.settings")
django.setup()

from pymongo import MongoClient
from hospital.Views.cashcounter import parse_payment_split
from hospital.Views.MasterAccountsReport.core_ledger_engine import AccountsLedgerEngine
from hospital.services.core_payment_ledger import (
    clean_numeric,
    get_shift_aliases,
    is_cash_return_or_refund,
)

IST = timezone(timedelta(hours=5, minutes=30))
START_DATE = date(2026, 11, 15)
END_DATE = date(2026, 11, 26)

# IST [2026-11-15 00:00:00, 2026-11-26 23:59:59.999999] in naive UTC
START_UTC = datetime(2026, 11, 14, 18, 30, 0)
END_UTC = datetime(2026, 11, 26, 18, 29, 59, 999999)


def to_ist_dt(val):
    """Convert naive-UTC datetime, aware datetime, date, or ISO/DMY string to naive IST datetime."""
    if not val:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val + timedelta(hours=5, minutes=30)
        return val.astimezone(IST).replace(tzinfo=None)
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt + timedelta(hours=5, minutes=30)
            return dt.astimezone(IST).replace(tzinfo=None)
        except Exception:
            pass
        for fmt in (
            "%d/%m/%Y %I:%M %p",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d-%m-%Y %I:%M %p",
            "%d-%m-%Y",
            "%d/%m/%Y",
        ):
            try:
                return datetime.strptime(s[:26], fmt)
            except Exception:
                continue
    return None


def fmt_ist_date(val):
    dt = to_ist_dt(val)
    return dt.strftime("%Y-%m-%d") if dt else ""


def fmt_ist_dt(val):
    dt = to_ist_dt(val)
    return dt.strftime("%Y-%m-%d %I:%M %p") if dt else ""


def fmt_shift_date(shift_doc):
    """Resolve canonical YYYY-MM-DD shift date from shift.date or StartingTime (IST)."""
    d = shift_doc.get("date")
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, str) and len(d.strip()) >= 10:
        return d.strip()[:10]
    return fmt_ist_date(shift_doc.get("StartingTime"))


def is_credit_or_insurance_mode(doc):
    """Identify whether a pending/billed document is Credit / Insurance rather than Cash-counter collectible."""
    pd = doc.get("payment_details") or {}
    if not isinstance(pd, dict):
        pd = {}
    candidates = [
        doc.get("payment_method"),
        doc.get("paymentMethod"),
        doc.get("payment_mode"),
        doc.get("PaymentType"),
        doc.get("billing_mode"),
        pd.get("method"),
        pd.get("payment_mode"),
    ]
    if doc.get("is_insurance") or doc.get("is_insurance_bill"):
        return True
    for c in candidates:
        s = str(c or "").strip().lower()
        if not s:
            continue
        if any(k in s for k in ["credit", "insurance", "tpa", "cghs", "echs", "esic", "esi", "railway", "scheme", "tncmchis"]):
            return True
    return False


def extract_pharmacy_discount(doc):
    """Extract discount amount from a hospital_pharmacybilling document."""
    disc = clean_numeric(doc.get("overall_discount_amount")) or clean_numeric(doc.get("discount_amount"))
    if disc <= 0:
        disc = clean_numeric(doc.get("total_item_discount"))
    if disc <= 0:
        meds = doc.get("medicine_particulars") or []
        if isinstance(meds, str):
            try:
                meds = json.loads(meds)
            except Exception:
                meds = []
        if isinstance(meds, list):
            disc = sum(
                clean_numeric(m.get("discount") or m.get("discount_amount") or m.get("discountAmount"))
                for m in meds
                if isinstance(m, dict)
            )
    if disc <= 0 and clean_numeric(doc.get("overall_discount_value")) > 0:
        tot = clean_numeric(doc.get("total_amount"))
        dt = str(doc.get("overall_discount_type") or "percent").lower()
        dval = clean_numeric(doc.get("overall_discount_value"))
        disc = (tot * dval / 100.0) if dt == "percent" else dval
    return round(max(0.0, disc), 2)


def extract_invest_discount(doc):
    """Extract discount amount from a hospital_investbilling document."""
    disc = clean_numeric(doc.get("discount"))
    if disc <= 0:
        items = doc.get("item") or []
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        if isinstance(items, list):
            disc = sum(
                clean_numeric(it.get("discount") or it.get("discountAmount") or it.get("discount_amount"))
                for it in items
                if isinstance(it, dict)
            )
    if disc <= 0 and clean_numeric(doc.get("discountPercent")) > 0:
        disc = clean_numeric(doc.get("total")) * clean_numeric(doc.get("discountPercent")) / 100.0
    return round(max(0.0, disc), 2)


def extract_discharge_discount(doc):
    """Extract discount amount from a hospital_dischargebilling document."""
    disc = clean_numeric(doc.get("discount_amount") or doc.get("total_disc"))
    if disc <= 0 and clean_numeric(doc.get("discount_percent")) > 0:
        disc = clean_numeric(doc.get("total_amount")) * clean_numeric(doc.get("discount_percent")) / 100.0
    return round(max(0.0, disc), 2)


def batch_calculate_shift_collections(db, shift_nos):
    """Batched equivalent of cashcounter.calculate_shift_collection(shift_no) across all shifts."""
    alias_to_canon = {}
    all_aliases = []
    for s_no in shift_nos:
        for al in (get_shift_aliases(s_no) or [s_no]):
            alias_to_canon[al] = s_no
            alias_to_canon[str(al)] = s_no
            all_aliases.append(al)
    all_aliases = list(set(all_aliases))

    def resolve_shift(val):
        if val is None:
            return None
        return alias_to_canon.get(val) or alias_to_canon.get(str(val).strip())

    results = {
        s_no: {
            "total_collection": 0.0,
            "total_credit": 0.0,
            "ip_advance": 0.0,
            "sales_return": 0.0,
            "receipts": 0.0,
            "payments": 0.0,
        }
        for s_no in shift_nos
    }
    if not all_aliases:
        return results

    for b in db["hospital_billing"].find(
        {"shiftno": {"$in": all_aliases}, "payment_status": {"$in": ["Paid", "Billing"]}, "is_active": {"$ne": False}},
        {"shiftno": 1, "total_fees": 1, "payment_details": 1, "payment_method": 1, "payment_mode": 1},
    ):
        sno = resolve_shift(b.get("shiftno"))
        if sno:
            c_amt, cr_amt = parse_payment_split(b, clean_numeric(b.get("total_fees", 0)))
            results[sno]["total_collection"] += c_amt
            results[sno]["total_credit"] += cr_amt

    for d in db["hospital_investbilling"].find(
        {"shiftno": {"$in": all_aliases}, "paymentStatus": "Paid"},
        {"shiftno": 1, "finalPrice": 1, "total": 1, "payment_details": 1, "payment_method": 1, "payment_mode": 1},
    ):
        sno = resolve_shift(d.get("shiftno"))
        if sno:
            c_amt, cr_amt = parse_payment_split(d, clean_numeric(d.get("finalPrice") or d.get("total") or 0))
            results[sno]["total_collection"] += c_amt
            results[sno]["total_credit"] += cr_amt

    for d in db["hospital_dischargebilling"].find(
        {"shiftno": {"$in": all_aliases}, "status": "Paid"},
        {"shiftno": 1, "net_amount": 1, "payment_details": 1, "payment_method": 1, "payment_mode": 1},
    ):
        sno = resolve_shift(d.get("shiftno"))
        if sno:
            dis_amt = clean_numeric(d.get("net_amount", 0))
            c_amt, cr_amt = parse_payment_split(d, dis_amt)
            if dis_amt < 0:
                c_amt, cr_amt = -abs(c_amt), -abs(cr_amt)
            results[sno]["total_collection"] += c_amt
            results[sno]["total_credit"] += cr_amt

    for d in db["hospital_pharmacybilling"].find(
        {"shiftno": {"$in": all_aliases}, "billing_status": "Paid"},
        {"shiftno": 1, "net_amount": 1, "payment_details": 1, "payment_method": 1, "payment_mode": 1},
    ):
        sno = resolve_shift(d.get("shiftno"))
        if sno:
            c_amt, cr_amt = parse_payment_split(d, clean_numeric(d.get("net_amount", 0)))
            results[sno]["total_collection"] += c_amt
            results[sno]["total_credit"] += cr_amt

    counted_adv = defaultdict(set)
    for adm in db["hospital_admission"].find({"advance_payments.shiftno": {"$in": all_aliases}}, {"advance_payments": 1}):
        payments = adm.get("advance_payments", [])
        if isinstance(payments, str):
            try:
                payments = json.loads(payments)
            except Exception:
                try:
                    payments = ast.literal_eval(payments)
                except Exception:
                    payments = []
        if not isinstance(payments, list):
            continue
        for p in payments:
            if not isinstance(p, dict):
                continue
            sno = resolve_shift(p.get("shiftno"))
            if not sno:
                continue
            bill_no = p.get("bill_no")
            if bill_no and bill_no not in counted_adv[sno] and str(p.get("status", "")).lower() == "paid":
                amt = clean_numeric(p.get("advance_amount", 0))
                results[sno]["ip_advance"] += amt
                c_amt, cr_amt = parse_payment_split(p, amt)
                results[sno]["total_collection"] += c_amt
                results[sno]["total_credit"] += cr_amt
                counted_adv[sno].add(bill_no)

    for col_name, amt_fields in [
        ("hospital_salesreturn", ["return_amount", "amount"]),
        ("hospital_refund", ["refund_amount", "amount"]),
        ("hospital_investrefund", ["refund_finalPrice", "refund_amount", "amount"]),
        ("hospital_ipadvance_refund", ["refund_amount", "advance_amount", "amount"]),
    ]:
        for r in db[col_name].find(
            {"shiftno": {"$in": all_aliases}},
            {"shiftno": 1, "return_amount": 1, "refund_amount": 1, "refund_finalPrice": 1, "advance_amount": 1, "amount": 1,
             "payment_details": 1, "payment_method": 1, "PaymentType": 1, "payment_mode": 1},
        ):
            sno = resolve_shift(r.get("shiftno"))
            if not sno:
                continue
            amt = 0.0
            for fld in amt_fields:
                if r.get(fld):
                    amt = clean_numeric(r.get(fld))
                    break
            if amt == 0.0 and isinstance(r.get("payment_details"), dict):
                amt = clean_numeric(r["payment_details"].get("Paid_amount", 0))
            if is_cash_return_or_refund(r):
                results[sno]["sales_return"] += amt

    for d in db["hospital_receiptandpayment"].find(
        {"shiftno": {"$in": all_aliases}},
        {"shiftno": 1, "amount": 1, "receipt_type": 1, "payment_details": 1, "payment_method": 1, "payment_mode": 1, "mode_of_payment": 1},
    ):
        sno = resolve_shift(d.get("shiftno"))
        if not sno:
            continue
        amt = clean_numeric(d.get("amount", 0))
        if d.get("receipt_type") == "Receipt":
            results[sno]["receipts"] += amt
            c_amt, cr_amt = parse_payment_split(d, amt)
            results[sno]["total_collection"] += c_amt
            results[sno]["total_credit"] += cr_amt
        elif d.get("receipt_type") == "Payment":
            results[sno]["payments"] += amt
            results[sno]["total_collection"] -= amt

    return results


def summarize_ledger_bills(bills, exp_docs):
    """Aggregate enriched AccountsLedgerEngine bills + Payment-only expense vouchers."""
    gross_cash = 0.0
    card_bank = 0.0
    credit_scheme = 0.0
    returns_refunds = 0.0
    receipts = 0.0
    expenses_in_ccc = 0.0

    for b in bills:
        cat_u = str(b.get("category") or "").upper()
        if b.get("is_expense") or cat_u == "EXPENSE PAYMENT":
            expenses_in_ccc += abs(clean_numeric(b.get("expense_amount") or b.get("amount") or b.get("cash")))
            continue
        if b.get("is_sales_return") or b.get("is_refund") or cat_u in (
            "SALES RETURN", "REFUND", "DISCHARGE REFUND", "INVESTIGATION REFUND", "OP REFUND", "IP ADVANCE REFUND"
        ):
            returns_refunds += abs(clean_numeric(b.get("refund_amount") or b.get("return_amount") or b.get("sales_return") or b.get("amount")))
            continue

        c_val = clean_numeric(b.get("cash"))
        b_val = clean_numeric(b.get("bank"))
        cr_val = clean_numeric(b.get("credit"))
        if c_val > 0:
            gross_cash += c_val
        card_bank += b_val
        credit_scheme += cr_val
        if cat_u == "MISCELLANEOUS":
            receipts += clean_numeric(b.get("amount") or b.get("net_amount"))

    exp_payment_only = sum(
        clean_numeric(e.get("amount"))
        for e in exp_docs
        if str(e.get("receipt_type") or "").strip().lower() == "payment"
    )
    expenses = exp_payment_only if exp_payment_only > 0 else expenses_in_ccc

    gross_cash = round(gross_cash, 2)
    card_bank = round(card_bank, 2)
    credit_scheme = round(credit_scheme, 2)
    returns_refunds = round(returns_refunds, 2)
    expenses = round(expenses, 2)
    receipts = round(receipts, 2)
    total_collection = round(gross_cash + card_bank + credit_scheme, 2)
    net_handover = round(gross_cash - expenses - returns_refunds, 2)

    return {
        "bill_count": len(bills),
        "gross_cash": gross_cash,
        "card_bank": card_bank,
        "credit_scheme": credit_scheme,
        "total_collection": total_collection,
        "receipts": receipts,
        "expenses": expenses,
        "returns_refunds": returns_refunds,
        "net_handover": net_handover,
    }


def main():
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db = client["HMS"]
    g_db = client["Global"]

    outlet_map = {
        str(o.get("outlet_code")).strip(): str(o.get("outlet_name") or "").strip()
        for o in db["hospital_outlets"].find({}, {"outlet_code": 1, "outlet_name": 1})
        if o.get("outlet_code")
    }
    counter_map = {
        str(c.get("counter_id")).strip(): str(c.get("counter_name") or "").strip()
        for c in db["hospital_cashcounter"].find({}, {"counter_id": 1, "counter_name": 1})
        if c.get("counter_id")
    }
    cashier_map = {
        str(p.get("employeeId")).strip(): str(p.get("employeeName") or "").strip()
        for p in g_db["backend_diagnostics_profile"].find({}, {"employeeId": 1, "employeeName": 1})
        if p.get("employeeId")
    }

    # =========================================================================
    # 1. SHIFTS, MODULE CALCULATION, AND ENRICHED LEDGER (2026-11-15 to 2026-11-26)
    # =========================================================================
    shift_docs = list(
        db["hospital_cashcountershiftdetails"].find({
            "$or": [
                {"date": {"$gte": datetime(2026, 11, 15, 0, 0), "$lte": datetime(2026, 11, 26, 23, 59, 59)}},
                {"StartingTime": {"$gte": START_UTC, "$lte": END_UTC}},
            ]
        }).sort([("date", 1), ("StartingTime", 1), ("shiftno", 1)])
    )

    filtered_shifts = []
    seen_shifts = set()
    for s in shift_docs:
        shift_no = str(s.get("shiftno") or "").strip()
        if not shift_no or shift_no in seen_shifts:
            continue
        seen_shifts.add(shift_no)

        s_date = fmt_shift_date(s)
        if not (START_DATE.strftime("%Y-%m-%d") <= s_date <= END_DATE.strftime("%Y-%m-%d")):
            st_ist = fmt_ist_date(s.get("StartingTime"))
            if not (START_DATE.strftime("%Y-%m-%d") <= st_ist <= END_DATE.strftime("%Y-%m-%d")):
                continue
            s_date = st_ist
        filtered_shifts.append((s_date, s))

    shift_nos = [str(s.get("shiftno")).strip() for _, s in filtered_shifts]
    calc_by_shift = batch_calculate_shift_collections(db, shift_nos)

    ledger_res = AccountsLedgerEngine.get_ledger_data(
        from_str=START_DATE.strftime("%Y-%m-%d"),
        to_str=END_DATE.strftime("%Y-%m-%d"),
        force_refresh=True,
    )
    ledger_bills_all = ledger_res.get("bills", [])

    alias_to_canon = {}
    all_aliases = []
    for sno in shift_nos:
        for al in (get_shift_aliases(sno) or [sno]):
            alias_to_canon[al] = sno
            alias_to_canon[str(al)] = sno
            all_aliases.append(al)

    rp_docs_all = list(db["hospital_receiptandpayment"].find({
        "$or": [
            {"created_date": {"$gte": START_UTC, "$lte": END_UTC}},
            {"voucher_date": {"$gte": START_UTC, "$lte": END_UTC}},
            {"shiftno": {"$in": list(set(all_aliases))}},
        ]
    }))
    rp_seen = set()
    rp_unique = []
    for r in rp_docs_all:
        rid = r.get("_id")
        if rid not in rp_seen:
            rp_seen.add(rid)
            rp_unique.append(r)

    rp_by_shift = defaultdict(list)
    rp_by_date = defaultdict(list)
    rp_by_outlet = defaultdict(list)
    for r in rp_unique:
        sno = alias_to_canon.get(r.get("shiftno")) or alias_to_canon.get(str(r.get("shiftno") or "").strip())
        if sno:
            rp_by_shift[sno].append(r)
        dt_val = r.get("created_date") or r.get("voucher_date")
        d_ist = fmt_ist_date(dt_val)
        if d_ist and (START_DATE.strftime("%Y-%m-%d") <= d_ist <= END_DATE.strftime("%Y-%m-%d")):
            rp_by_date[d_ist].append(r)
            oc = str(r.get("outlet_code") or "").strip() or "OLET003"
            rp_by_outlet[oc].append(r)

    ledger_bills_by_shift = defaultdict(list)
    ledger_bills_by_date = defaultdict(list)
    ledger_bills_by_outlet = defaultdict(list)
    for b in ledger_bills_all:
        raw_sno = str(b.get("shift_no") or "").strip()
        sno = alias_to_canon.get(raw_sno) or alias_to_canon.get(raw_sno.replace("/", "")) or raw_sno
        if sno:
            ledger_bills_by_shift[sno].append(b)
        d_ist = fmt_ist_date(b.get("date"))
        if d_ist and (START_DATE.strftime("%Y-%m-%d") <= d_ist <= END_DATE.strftime("%Y-%m-%d")):
            ledger_bills_by_date[d_ist].append(b)
        oc = str(b.get("outlet_code") or "").strip() or "OLET003"
        ledger_bills_by_outlet[oc].append(b)

    # =========================================================================
    # 2. DISCOUNTS (Pharmacy, Investigation, Discharge) BY SHIFT, DATE, OUTLET, MODULE
    # =========================================================================
    disc_by_date = defaultdict(lambda: {
        "paid_pharm": 0.0, "paid_invest": 0.0, "paid_disch": 0.0, "paid_total": 0.0, "paid_cnt": 0,
        "all_pharm": 0.0, "all_invest": 0.0, "all_disch": 0.0, "all_total": 0.0, "all_cnt": 0,
    })
    disc_by_shift = defaultdict(lambda: {"pharm": 0.0, "invest": 0.0, "disch": 0.0, "total": 0.0, "cnt": 0})
    disc_by_outlet = defaultdict(lambda: {"paid_total": 0.0, "paid_cnt": 0, "all_total": 0.0, "all_cnt": 0})
    disc_by_module = defaultdict(lambda: {"paid_amt": 0.0, "paid_cnt": 0, "all_amt": 0.0, "all_cnt": 0})

    def record_discount(d_str, sno, outlet_c, mod_key, disc_amt, is_paid):
        if disc_amt <= 0:
            return
        if not d_str or not (START_DATE.strftime("%Y-%m-%d") <= d_str <= END_DATE.strftime("%Y-%m-%d")):
            return
        dd = disc_by_date[d_str]
        dd[f"all_{mod_key}"] = round(dd[f"all_{mod_key}"] + disc_amt, 2)
        dd["all_total"] = round(dd["all_total"] + disc_amt, 2)
        dd["all_cnt"] += 1

        dm = disc_by_module[mod_key]
        dm["all_amt"] = round(dm["all_amt"] + disc_amt, 2)
        dm["all_cnt"] += 1

        oc = outlet_c or "UNKNOWN"
        do = disc_by_outlet[oc]
        do["all_total"] = round(do["all_total"] + disc_amt, 2)
        do["all_cnt"] += 1

        if is_paid:
            dd[f"paid_{mod_key}"] = round(dd[f"paid_{mod_key}"] + disc_amt, 2)
            dd["paid_total"] = round(dd["paid_total"] + disc_amt, 2)
            dd["paid_cnt"] += 1

            dm["paid_amt"] = round(dm["paid_amt"] + disc_amt, 2)
            dm["paid_cnt"] += 1

            do["paid_total"] = round(do["paid_total"] + disc_amt, 2)
            do["paid_cnt"] += 1

            if sno:
                ds = disc_by_shift[sno]
                ds[mod_key] = round(ds[mod_key] + disc_amt, 2)
                ds["total"] = round(ds["total"] + disc_amt, 2)
                ds["cnt"] += 1

    # Pharmacy discounts
    for doc in db["hospital_pharmacybilling"].find({
        "is_deleted": {"$ne": True},
        "is_cancelled": {"$ne": True},
        "$or": [
            {"bill_date": {"$gte": START_UTC, "$lte": END_UTC}},
            {"created_date": {"$gte": START_UTC, "$lte": END_UTC}},
            {"shiftno": {"$in": list(set(all_aliases))}},
        ],
    }, {
        "bill_date": 1, "created_date": 1, "paid_date": 1, "shiftno": 1, "outlet_code": 1,
        "billing_status": 1, "total_amount": 1, "discount_amount": 1, "overall_discount_amount": 1,
        "overall_discount_value": 1, "overall_discount_type": 1, "total_item_discount": 1, "medicine_particulars": 1,
    }):
        disc = extract_pharmacy_discount(doc)
        if disc <= 0:
            continue
        raw_sno = str(doc.get("shiftno") or "").strip()
        sno = alias_to_canon.get(raw_sno) or alias_to_canon.get(raw_sno.replace("/", "")) or raw_sno
        d_str = fmt_ist_date(doc.get("bill_date") or doc.get("created_date"))
        is_paid = (str(doc.get("billing_status") or "") in ("Paid", "Completed")) or bool(raw_sno)
        record_discount(d_str, sno, str(doc.get("outlet_code") or "").strip(), "pharm", disc, is_paid)

    # Investigation discounts
    for doc in db["hospital_investbilling"].find({
        "is_active": {"$ne": False},
        "is_cancelled": {"$ne": True},
        "$or": [
            {"investBillDate": {"$gte": START_UTC, "$lte": END_UTC}},
            {"shiftno": {"$in": list(set(all_aliases))}},
        ],
    }, {
        "investBillDate": 1, "created_date": 1, "shiftno": 1, "outlet_code": 1,
        "paymentStatus": 1, "total": 1, "discount": 1, "discountPercent": 1, "item": 1,
    }):
        disc = extract_invest_discount(doc)
        if disc <= 0:
            continue
        raw_sno = str(doc.get("shiftno") or "").strip()
        sno = alias_to_canon.get(raw_sno) or alias_to_canon.get(raw_sno.replace("/", "")) or raw_sno
        d_str = fmt_ist_date(doc.get("investBillDate") or doc.get("created_date"))
        is_paid = (str(doc.get("paymentStatus") or "") == "Paid") or bool(raw_sno)
        record_discount(d_str, sno, str(doc.get("outlet_code") or "").strip(), "invest", disc, is_paid)

    # Discharge discounts
    for doc in db["hospital_dischargebilling"].find({
        "is_cancelled": {"$ne": True},
        "is_active": {"$ne": False},
        "$or": [
            {"bill_date": {"$gte": START_UTC, "$lte": END_UTC}},
            {"shiftno": {"$in": list(set(all_aliases))}},
        ],
    }, {
        "bill_date": 1, "created_date": 1, "shiftno": 1, "outlet_code": 1,
        "status": 1, "total_amount": 1, "discount_amount": 1, "total_disc": 1, "discount_percent": 1,
    }):
        disc = extract_discharge_discount(doc)
        if disc <= 0:
            continue
        raw_sno = str(doc.get("shiftno") or "").strip()
        sno = alias_to_canon.get(raw_sno) or alias_to_canon.get(raw_sno.replace("/", "")) or raw_sno
        d_str = fmt_ist_date(doc.get("bill_date") or doc.get("created_date"))
        is_paid = (str(doc.get("status") or "") == "Paid") or bool(raw_sno)
        record_discount(d_str, sno, str(doc.get("outlet_code") or "").strip(), "disch", disc, is_paid)

    # =========================================================================
    # 3. BUILD SHIFT ROWS
    # =========================================================================
    shift_rows = []
    for s_date, s in filtered_shifts:
        shift_no = str(s.get("shiftno")).strip()
        outlet_code = str(s.get("outlet_code") or s.get("SelectedOutlet") or "").strip()
        outlet_name = outlet_map.get(outlet_code, outlet_code)
        counter_id = str(s.get("CashCounter") or "").strip()
        counter_name = counter_map.get(counter_id, counter_id)
        cashier_id = str(s.get("CashierID") or "").strip()
        cashier_name = cashier_map.get(cashier_id, cashier_id)
        shift_status = str(s.get("ShiftStatus") or ("active" if s.get("is_active") else "inactive")).strip()

        open_bal = round(clean_numeric(s.get("OpeningBalance")), 2)
        stored_cash = round(clean_numeric(s.get("collected_Amount")), 2)
        stored_credit = round(clean_numeric(s.get("CreditAmount")), 2)
        stored_ret = round(clean_numeric(s.get("SalesReturnAmount")), 2)
        stored_close = round(clean_numeric(s.get("ClosingBalance")), 2)

        calc = calc_by_shift.get(shift_no, {})
        calc_cash = round(calc.get("total_collection", 0.0), 2)
        calc_credit = round(calc.get("total_credit", 0.0), 2)
        calc_ret = round(calc.get("sales_return", 0.0), 2)
        calc_exp = round(calc.get("payments", 0.0), 2)
        calc_ipadv = round(calc.get("ip_advance", 0.0), 2)

        lm = summarize_ledger_bills(ledger_bills_by_shift.get(shift_no, []), rp_by_shift.get(shift_no, []))
        ledger_cash_after_exp = round(lm["gross_cash"] - lm["expenses"], 2)
        ledger_non_cash = round(lm["card_bank"] + lm["credit_scheme"], 2)
        s_disc = disc_by_shift.get(shift_no, {"total": 0.0, "cnt": 0})

        cash_diff_calc = round(stored_cash - calc_cash, 2)
        credit_diff_calc = round(stored_credit - calc_credit, 2)
        cash_diff_ledger = round(stored_cash - ledger_cash_after_exp, 2)
        credit_diff_ledger = round(stored_credit - ledger_non_cash, 2)

        if shift_status.lower() == "active":
            tally_status = "ACTIVE (OPEN)"
        elif abs(cash_diff_calc) <= 0.05 and abs(credit_diff_calc) <= 0.05 and abs(stored_ret - calc_ret) <= 0.05:
            tally_status = "TALLIED (MODULE)"
        elif abs(cash_diff_ledger) <= 1.0 and abs(credit_diff_ledger) <= 1.0:
            tally_status = "TALLIED (LEDGER)"
        else:
            tally_status = "VARIANCE"

        shift_rows.append({
            "date": s_date,
            "shift_no": shift_no,
            "outlet_code": outlet_code,
            "outlet_name": outlet_name,
            "counter_id": counter_id,
            "counter_name": counter_name,
            "cashier_id": cashier_id,
            "cashier_name": cashier_name,
            "start_time_ist": fmt_ist_dt(s.get("StartingTime")),
            "end_time_ist": fmt_ist_dt(s.get("closingTime")) if s.get("closingTime") else "ACTIVE",
            "shift_status": shift_status,
            "opening_balance": open_bal,
            "stored_cash": stored_cash,
            "stored_credit": stored_credit,
            "stored_return": stored_ret,
            "stored_closing": stored_close,
            "calc_cash": calc_cash,
            "calc_credit": calc_credit,
            "calc_expenses": calc_exp,
            "calc_returns": calc_ret,
            "calc_ip_advance": calc_ipadv,
            "ledger_count": lm["bill_count"],
            "ledger_gross_cash": lm["gross_cash"],
            "ledger_card_bank": lm["card_bank"],
            "ledger_credit_scheme": lm["credit_scheme"],
            "ledger_total_collection": lm["total_collection"],
            "ledger_expenses": lm["expenses"],
            "ledger_returns": lm["returns_refunds"],
            "ledger_net_handover": lm["net_handover"],
            "shift_discount": round(s_disc["total"], 2),
            "shift_discount_bills": s_disc["cnt"],
            "cash_diff_calc": cash_diff_calc,
            "credit_diff_calc": credit_diff_calc,
            "cash_diff_ledger": cash_diff_ledger,
            "credit_diff_ledger": credit_diff_ledger,
            "tally_status": tally_status,
        })

    # =========================================================================
    # 4. DATE-WISE PENDING BILLS (2026-11-15 to 2026-11-26)
    # =========================================================================
    pending_agg = defaultdict(lambda: {
        "cash_cnt": 0, "cash_amt": 0.0,
        "credit_cnt": 0, "credit_amt": 0.0,
        "zero_cnt": 0,
    })

    def add_pending(d_str, module, amt, is_credit):
        if not d_str or not (START_DATE.strftime("%Y-%m-%d") <= d_str <= END_DATE.strftime("%Y-%m-%d")):
            return
        bucket = pending_agg[(d_str, module)]
        if abs(amt) < 0.005:
            bucket["zero_cnt"] += 1
        if is_credit:
            bucket["credit_cnt"] += 1
            bucket["credit_amt"] = round(bucket["credit_amt"] + amt, 2)
        else:
            bucket["cash_cnt"] += 1
            bucket["cash_amt"] = round(bucket["cash_amt"] + amt, 2)

    for b in db["hospital_billing"].find({
        "billed_date": {"$gte": START_UTC, "$lte": END_UTC},
        "payment_status": {"$in": ["Pending", "Cash Pending"]},
        "is_cancelled": {"$ne": True},
        "is_active": {"$ne": False},
    }, {"billed_date": 1, "total_fees": 1, "payment_method": 1, "payment_mode": 1, "payment_details": 1}):
        add_pending(fmt_ist_date(b.get("billed_date")), "OP Registration / Billing", clean_numeric(b.get("total_fees")), is_credit_or_insurance_mode(b))

    for inv in db["hospital_investbilling"].find({
        "investBillDate": {"$gte": START_UTC, "$lte": END_UTC},
        "paymentStatus": "Pending",
        "is_cancelled": {"$ne": True},
        "is_active": {"$ne": False},
    }, {"investBillDate": 1, "finalPrice": 1, "total": 1, "paymentMethod": 1, "payment_method": 1, "payment_mode": 1, "payment_details": 1}):
        amt = clean_numeric(inv.get("finalPrice") if inv.get("finalPrice") is not None else inv.get("total"))
        add_pending(fmt_ist_date(inv.get("investBillDate")), "Investigation", amt, is_credit_or_insurance_mode(inv))

    for dis in db["hospital_dischargebilling"].find({
        "bill_date": {"$gte": START_UTC, "$lte": END_UTC},
        "status": {"$in": ["Billed", "Pending"]},
        "is_cancelled": {"$ne": True},
        "is_active": {"$ne": False},
    }, {"bill_date": 1, "net_amount": 1, "payment_method": 1, "payment_mode": 1, "is_insurance_bill": 1, "payment_details": 1}):
        add_pending(fmt_ist_date(dis.get("bill_date")), "Discharge", clean_numeric(dis.get("net_amount")), is_credit_or_insurance_mode(dis))

    for ph in db["hospital_pharmacybilling"].find({
        "bill_date": {"$gte": START_UTC, "$lte": END_UTC},
        "billing_status": {"$in": ["Billed", "Pending"]},
        "is_deleted": {"$ne": True},
        "is_cancelled": {"$ne": True},
    }, {"bill_date": 1, "created_date": 1, "net_amount": 1, "payment_mode": 1, "payment_method": 1, "billing_mode": 1, "is_insurance": 1, "payment_details": 1}):
        add_pending(fmt_ist_date(ph.get("bill_date") or ph.get("created_date")), "Pharmacy", clean_numeric(ph.get("net_amount")), is_credit_or_insurance_mode(ph))

    for adm in db["hospital_admission"].find({"advance_payments.status": {"$in": ["Pending", "pending", "PENDING"]}}, {"advance_payments": 1}):
        for p in (adm.get("advance_payments") or []):
            if not isinstance(p, dict) or str(p.get("status") or "").strip().lower() != "pending":
                continue
            dt_str = fmt_ist_date(p.get("bill_date") or p.get("date") or p.get("created_date"))
            amt = clean_numeric(p.get("advance_amount") or p.get("amount"))
            add_pending(dt_str, "IP Advance", amt, is_credit_or_insurance_mode(p))

    for sr in db["hospital_salesreturn"].find({"created_date": {"$gte": START_UTC, "$lte": END_UTC}, "status": "Pending"}, {"created_date": 1, "return_amount": 1, "amount": 1, "PaymentType": 1, "payment_mode": 1}):
        add_pending(fmt_ist_date(sr.get("created_date")), "Sales Return / Refund", clean_numeric(sr.get("return_amount") or sr.get("amount")), is_credit_or_insurance_mode(sr))

    for rf in db["hospital_refund"].find({"created_date": {"$gte": START_UTC, "$lte": END_UTC}, "status": "Pending"}, {"created_date": 1, "refund_amount": 1, "amount": 1, "payment_mode": 1}):
        add_pending(fmt_ist_date(rf.get("created_date")), "Sales Return / Refund", clean_numeric(rf.get("refund_amount") or rf.get("amount")), is_credit_or_insurance_mode(rf))

    all_dates = [(START_DATE + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((END_DATE - START_DATE).days + 1)]
    modules_order = ["OP Registration / Billing", "Investigation", "Discharge", "Pharmacy", "IP Advance", "Sales Return / Refund"]

    # =========================================================================
    # 5. PREPARE DAILY EXECUTIVE DATA
    # =========================================================================
    exec_rows = []
    for d_str in all_dates:
        d_shifts = [r for r in shift_rows if r["date"] == d_str]
        d_lm = summarize_ledger_bills(ledger_bills_by_date.get(d_str, []), rp_by_date.get(d_str, []))
        dd = disc_by_date[d_str]
        d_p_cash_c = sum(pending_agg[(d_str, m)]["cash_cnt"] for m in modules_order)
        d_p_cash_a = round(sum(pending_agg[(d_str, m)]["cash_amt"] for m in modules_order), 2)
        d_p_cred_c = sum(pending_agg[(d_str, m)]["credit_cnt"] for m in modules_order)
        d_p_cred_a = round(sum(pending_agg[(d_str, m)]["credit_amt"] for m in modules_order), 2)
        d_p_zero_c = sum(pending_agg[(d_str, m)]["zero_cnt"] for m in modules_order)

        exec_rows.append({
            "date": d_str,
            "total_shifts": len(d_shifts),
            "active_shifts": sum(1 for r in d_shifts if r["shift_status"].lower() == "active"),
            "closed_shifts": sum(1 for r in d_shifts if r["shift_status"].lower() != "active"),
            "stored_cash": round(sum(r["stored_cash"] for r in d_shifts), 2),
            "stored_credit": round(sum(r["stored_credit"] for r in d_shifts), 2),
            "stored_return": round(sum(r["stored_return"] for r in d_shifts), 2),
            "stored_closing": round(sum(r["stored_closing"] for r in d_shifts), 2),
            "calc_cash": round(sum(r["calc_cash"] for r in d_shifts), 2),
            "calc_credit": round(sum(r["calc_credit"] for r in d_shifts), 2),
            "calc_exp": round(sum(r["calc_expenses"] for r in d_shifts), 2),
            "calc_ret": round(sum(r["calc_returns"] for r in d_shifts), 2),
            "led_gross_cash": d_lm["gross_cash"],
            "led_card_bank": d_lm["card_bank"],
            "led_credit_scheme": d_lm["credit_scheme"],
            "led_non_cash_total": round(d_lm["card_bank"] + d_lm["credit_scheme"], 2),
            "led_total": d_lm["total_collection"],
            "led_exp": d_lm["expenses"],
            "led_ret": d_lm["returns_refunds"],
            "led_net": d_lm["net_handover"],
            "paid_disc_pharm": dd["paid_pharm"],
            "paid_disc_invest": dd["paid_invest"],
            "paid_disc_disch": dd["paid_disch"],
            "paid_disc_total": dd["paid_total"],
            "paid_disc_cnt": dd["paid_cnt"],
            "all_disc_total": dd["all_total"],
            "all_disc_cnt": dd["all_cnt"],
            "gross_before_disc": round(d_lm["total_collection"] + dd["paid_total"], 2),
            "p_cash_c": d_p_cash_c,
            "p_cash_a": d_p_cash_a,
            "p_cred_c": d_p_cred_c,
            "p_cred_a": d_p_cred_a,
            "p_zero_c": d_p_zero_c,
        })

    # =========================================================================
    # CSV 1: CASH COUNTER CASH, CREDIT, DISCOUNT & TOTAL REPORT (15-26 NOV 2026)
    # =========================================================================
    cc_report_path = os.path.join(OUTPUT_DIR, "HMS_CashCounter_Cash_Credit_Discount_Report_15_to_26_Nov_2026.csv")
    with open(cc_report_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["SECTION 1: DAILY CASH COUNTER REPORT (CASH, CREDIT, DISCOUNT & TOTAL) — 15 NOV TO 26 NOV 2026 (IST)"])
        w.writerow([
            "Date (IST)", "Shifts",
            "Shift Stored Cash (Rs)", "Shift Stored Credit/Card (Rs)", "Shift Stored Total (Cash+Credit) (Rs)",
            "Ledger Gross Cash (Rs)", "Ledger Card/UPI/Bank (Rs)", "Ledger Credit/Scheme (Rs)", "Ledger Total Credit/Non-Cash (Rs)",
            "Net Collected Total (Cash+Card+Credit) (Rs)",
            "Counter Paid Discount (Rs)", "Pharmacy Discount (Rs)", "Investigation Discount (Rs)", "Discharge Discount (Rs)",
            "All Billed Discount incl. Pending (Rs)",
            "Gross Total Before Discount (Net Coll + Paid Disc) (Rs)",
            "Counter Expenses (Rs)", "Sales Returns/Refunds (Rs)", "Net Cash Handover (Rs)",
        ])
        for er in exec_rows:
            st_tot = round(er["stored_cash"] + er["stored_credit"], 2)
            w.writerow([
                er["date"], er["total_shifts"],
                f"{er['stored_cash']:.2f}", f"{er['stored_credit']:.2f}", f"{st_tot:.2f}",
                f"{er['led_gross_cash']:.2f}", f"{er['led_card_bank']:.2f}", f"{er['led_credit_scheme']:.2f}", f"{er['led_non_cash_total']:.2f}",
                f"{er['led_total']:.2f}",
                f"{er['paid_disc_total']:.2f}", f"{er['paid_disc_pharm']:.2f}", f"{er['paid_disc_invest']:.2f}", f"{er['paid_disc_disch']:.2f}",
                f"{er['all_disc_total']:.2f}",
                f"{er['gross_before_disc']:.2f}",
                f"{er['led_exp']:.2f}", f"{er['led_ret']:.2f}", f"{er['led_net']:.2f}",
            ])

        gt_st_cash = round(sum(r["stored_cash"] for r in exec_rows), 2)
        gt_st_cred = round(sum(r["stored_credit"] for r in exec_rows), 2)
        gt_led_cash = round(sum(r["led_gross_cash"] for r in exec_rows), 2)
        gt_led_card = round(sum(r["led_card_bank"] for r in exec_rows), 2)
        gt_led_cr = round(sum(r["led_credit_scheme"] for r in exec_rows), 2)
        gt_led_nc = round(sum(r["led_non_cash_total"] for r in exec_rows), 2)
        gt_led_tot = round(sum(r["led_total"] for r in exec_rows), 2)
        gt_pd_tot = round(sum(r["paid_disc_total"] for r in exec_rows), 2)
        gt_pd_ph = round(sum(r["paid_disc_pharm"] for r in exec_rows), 2)
        gt_pd_inv = round(sum(r["paid_disc_invest"] for r in exec_rows), 2)
        gt_pd_dis = round(sum(r["paid_disc_disch"] for r in exec_rows), 2)
        gt_ad_tot = round(sum(r["all_disc_total"] for r in exec_rows), 2)
        gt_gross = round(sum(r["gross_before_disc"] for r in exec_rows), 2)
        gt_exp = round(sum(r["led_exp"] for r in exec_rows), 2)
        gt_ret = round(sum(r["led_ret"] for r in exec_rows), 2)
        gt_net = round(sum(r["led_net"] for r in exec_rows), 2)

        w.writerow([
            "GRAND TOTAL (15-26 Nov)", sum(r["total_shifts"] for r in exec_rows),
            f"{gt_st_cash:.2f}", f"{gt_st_cred:.2f}", f"{round(gt_st_cash + gt_st_cred, 2):.2f}",
            f"{gt_led_cash:.2f}", f"{gt_led_card:.2f}", f"{gt_led_cr:.2f}", f"{gt_led_nc:.2f}",
            f"{gt_led_tot:.2f}",
            f"{gt_pd_tot:.2f}", f"{gt_pd_ph:.2f}", f"{gt_pd_inv:.2f}", f"{gt_pd_dis:.2f}",
            f"{gt_ad_tot:.2f}",
            f"{gt_gross:.2f}",
            f"{gt_exp:.2f}", f"{gt_ret:.2f}", f"{gt_net:.2f}",
        ])

        w.writerow([])
        w.writerow(["SECTION 2: OUTLET-WISE CASH COUNTER SUMMARY (15-26 NOV 2026)"])
        w.writerow([
            "Outlet Code", "Outlet Name", "Shifts",
            "Shift Stored Cash (Rs)", "Shift Stored Credit/Card (Rs)", "Shift Stored Return (Rs)", "Shift Stored Closing (Rs)",
            "Ledger Gross Cash (Rs)", "Ledger Card/UPI/Bank (Rs)", "Ledger Credit/Scheme (Rs)", "Ledger Net Collection (Rs)",
            "Counter Paid Discount (Rs)", "All Billed Discount (Rs)",
            "Counter Expenses (Rs)", "Sales Returns/Refunds (Rs)", "Net Cash Handover (Rs)",
        ])
        outlets_seen = sorted(set([r["outlet_code"] for r in shift_rows] + list(ledger_bills_by_outlet.keys())))
        for oc in outlets_seen:
            o_shifts = [r for r in shift_rows if r["outlet_code"] == oc]
            o_lm = summarize_ledger_bills(ledger_bills_by_outlet.get(oc, []), rp_by_outlet.get(oc, []))
            o_disc = disc_by_outlet.get(oc, {"paid_total": 0.0, "all_total": 0.0})
            if not o_shifts and o_lm["total_collection"] == 0 and o_disc["all_total"] == 0:
                continue
            w.writerow([
                oc, outlet_map.get(oc, oc), len(o_shifts),
                f"{sum(r['stored_cash'] for r in o_shifts):.2f}",
                f"{sum(r['stored_credit'] for r in o_shifts):.2f}",
                f"{sum(r['stored_return'] for r in o_shifts):.2f}",
                f"{sum(r['stored_closing'] for r in o_shifts):.2f}",
                f"{o_lm['gross_cash']:.2f}", f"{o_lm['card_bank']:.2f}", f"{o_lm['credit_scheme']:.2f}", f"{o_lm['total_collection']:.2f}",
                f"{o_disc['paid_total']:.2f}", f"{o_disc['all_total']:.2f}",
                f"{o_lm['expenses']:.2f}", f"{o_lm['returns_refunds']:.2f}", f"{o_lm['net_handover']:.2f}",
            ])

        w.writerow([])
        w.writerow(["SECTION 3: MODULE-WISE DISCOUNT SUMMARY (15-26 NOV 2026)"])
        w.writerow(["Module", "Counter Paid Discounted Bills", "Counter Paid Discount (Rs)", "All Billed Discounted Bills", "All Billed Discount (Rs)"])
        for mod_key, label in [("pharm", "Pharmacy"), ("invest", "Investigation"), ("disch", "Discharge")]:
            dm = disc_by_module[mod_key]
            w.writerow([label, dm["paid_cnt"], f"{dm['paid_amt']:.2f}", dm["all_cnt"], f"{dm['all_amt']:.2f}"])
        w.writerow([
            "TOTAL DISCOUNT",
            sum(disc_by_module[k]["paid_cnt"] for k in ("pharm", "invest", "disch")),
            f"{sum(disc_by_module[k]['paid_amt'] for k in ('pharm', 'invest', 'disch')):.2f}",
            sum(disc_by_module[k]["all_cnt"] for k in ("pharm", "invest", "disch")),
            f"{sum(disc_by_module[k]['all_amt'] for k in ('pharm', 'invest', 'disch')):.2f}",
        ])

    # =========================================================================
    # CSV 2: SHIFT TALLY SUMMARY
    # =========================================================================
    shift_csv_path = os.path.join(OUTPUT_DIR, "HMS_Shift_Tally_Summary_15_to_26_Nov_2026.csv")
    shift_headers = [
        "Date (IST)", "Shift No", "Outlet Code", "Outlet Name", "Counter ID", "Counter Name",
        "Cashier ID", "Cashier Name", "Start Time (IST)", "End Time (IST)", "Shift Status",
        "Opening Balance (Rs)", "Stored Cash (Rs)", "Stored Credit/Card (Rs)", "Stored Sales Return (Rs)", "Stored Closing Balance (Rs)",
        "Calc Module Cash (Rs)", "Calc Module Credit/Card (Rs)", "Calc Module Expenses (Rs)", "Calc Module Returns (Rs)", "Calc IP Advance (Rs)",
        "Ledger Bills", "Ledger Gross Cash (Rs)", "Ledger Card/UPI/Bank (Rs)", "Ledger Credit/Scheme (Rs)", "Ledger Total Collection (Rs)",
        "Shift Discount Bills", "Shift Discount (Rs)",
        "Ledger Expenses (Rs)", "Ledger Returns/Refunds (Rs)", "Ledger Net Cash Handover (Rs)",
        "Cash Diff (Stored - Calc) (Rs)", "Cash Diff (Stored - Ledger Gross-Exp) (Rs)", "Credit Diff (Stored - Ledger NonCash) (Rs)", "Tally Status",
    ]
    with open(shift_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(shift_headers)
        for r in shift_rows:
            w.writerow([
                r["date"], r["shift_no"], r["outlet_code"], r["outlet_name"], r["counter_id"], r["counter_name"],
                r["cashier_id"], r["cashier_name"], r["start_time_ist"], r["end_time_ist"], r["shift_status"],
                f"{r['opening_balance']:.2f}", f"{r['stored_cash']:.2f}", f"{r['stored_credit']:.2f}", f"{r['stored_return']:.2f}", f"{r['stored_closing']:.2f}",
                f"{r['calc_cash']:.2f}", f"{r['calc_credit']:.2f}", f"{r['calc_expenses']:.2f}", f"{r['calc_returns']:.2f}", f"{r['calc_ip_advance']:.2f}",
                r["ledger_count"], f"{r['ledger_gross_cash']:.2f}", f"{r['ledger_card_bank']:.2f}", f"{r['ledger_credit_scheme']:.2f}", f"{r['ledger_total_collection']:.2f}",
                r["shift_discount_bills"], f"{r['shift_discount']:.2f}",
                f"{r['ledger_expenses']:.2f}", f"{r['ledger_returns']:.2f}", f"{r['ledger_net_handover']:.2f}",
                f"{r['cash_diff_calc']:.2f}", f"{r['cash_diff_ledger']:.2f}", f"{r['credit_diff_ledger']:.2f}", r["tally_status"],
            ])
        w.writerow([
            "GRAND TOTAL", f"{len(shift_rows)} Shifts", "", "", "", "", "", "", "", "", "",
            f"{sum(r['opening_balance'] for r in shift_rows):.2f}",
            f"{sum(r['stored_cash'] for r in shift_rows):.2f}",
            f"{sum(r['stored_credit'] for r in shift_rows):.2f}",
            f"{sum(r['stored_return'] for r in shift_rows):.2f}",
            f"{sum(r['stored_closing'] for r in shift_rows):.2f}",
            f"{sum(r['calc_cash'] for r in shift_rows):.2f}",
            f"{sum(r['calc_credit'] for r in shift_rows):.2f}",
            f"{sum(r['calc_expenses'] for r in shift_rows):.2f}",
            f"{sum(r['calc_returns'] for r in shift_rows):.2f}",
            f"{sum(r['calc_ip_advance'] for r in shift_rows):.2f}",
            sum(r["ledger_count"] for r in shift_rows),
            f"{sum(r['ledger_gross_cash'] for r in shift_rows):.2f}",
            f"{sum(r['ledger_card_bank'] for r in shift_rows):.2f}",
            f"{sum(r['ledger_credit_scheme'] for r in shift_rows):.2f}",
            f"{sum(r['ledger_total_collection'] for r in shift_rows):.2f}",
            sum(r["shift_discount_bills"] for r in shift_rows),
            f"{sum(r['shift_discount'] for r in shift_rows):.2f}",
            f"{sum(r['ledger_expenses'] for r in shift_rows):.2f}",
            f"{sum(r['ledger_returns'] for r in shift_rows):.2f}",
            f"{sum(r['ledger_net_handover'] for r in shift_rows):.2f}",
            f"{sum(r['cash_diff_calc'] for r in shift_rows):.2f}",
            f"{sum(r['cash_diff_ledger'] for r in shift_rows):.2f}",
            f"{sum(r['credit_diff_ledger'] for r in shift_rows):.2f}",
            "",
        ])

    # =========================================================================
    # CSV 3: DAILY PENDING BILLS SUMMARY
    # =========================================================================
    pending_csv_path = os.path.join(OUTPUT_DIR, "HMS_Daily_Pending_Bills_Summary_15_to_26_Nov_2026.csv")
    pending_headers = [
        "Date (IST)", "Module",
        "Cash Pending Count", "Cash Pending Amount (Rs)",
        "Credit/Insurance Pending Count", "Credit/Insurance Pending Amount (Rs)",
        "Zero-Fee Pending Count",
        "Total Pending Count", "Total Pending Amount (Rs)",
    ]
    with open(pending_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(pending_headers)
        mod_totals = defaultdict(lambda: {"cash_cnt": 0, "cash_amt": 0.0, "credit_cnt": 0, "credit_amt": 0.0, "zero_cnt": 0})
        for d_str in all_dates:
            day_cc, day_ca, day_crc, day_cra, day_zc = 0, 0.0, 0, 0.0, 0
            for mod in modules_order:
                b = pending_agg.get((d_str, mod))
                if not b:
                    continue
                tot_cnt = b["cash_cnt"] + b["credit_cnt"]
                tot_amt = round(b["cash_amt"] + b["credit_amt"], 2)
                w.writerow([d_str, mod, b["cash_cnt"], f"{b['cash_amt']:.2f}", b["credit_cnt"], f"{b['credit_amt']:.2f}", b["zero_cnt"], tot_cnt, f"{tot_amt:.2f}"])
                day_cc += b["cash_cnt"]
                day_ca = round(day_ca + b["cash_amt"], 2)
                day_crc += b["credit_cnt"]
                day_cra = round(day_cra + b["credit_amt"], 2)
                day_zc += b["zero_cnt"]
                mt = mod_totals[mod]
                mt["cash_cnt"] += b["cash_cnt"]
                mt["cash_amt"] = round(mt["cash_amt"] + b["cash_amt"], 2)
                mt["credit_cnt"] += b["credit_cnt"]
                mt["credit_amt"] = round(mt["credit_amt"] + b["credit_amt"], 2)
                mt["zero_cnt"] += b["zero_cnt"]
            w.writerow([d_str, "DAY SUBTOTAL", day_cc, f"{day_ca:.2f}", day_crc, f"{day_cra:.2f}", day_zc, day_cc + day_crc, f"{round(day_ca + day_cra, 2):.2f}"])
        w.writerow([])
        for mod in modules_order:
            mt = mod_totals[mod]
            w.writerow(["MODULE TOTAL (15-26 Nov)", mod, mt["cash_cnt"], f"{mt['cash_amt']:.2f}", mt["credit_cnt"], f"{mt['credit_amt']:.2f}", mt["zero_cnt"], mt["cash_cnt"] + mt["credit_cnt"], f"{round(mt['cash_amt'] + mt['credit_amt'], 2):.2f}"])
        g_cc = sum(mt["cash_cnt"] for mt in mod_totals.values())
        g_ca = round(sum(mt["cash_amt"] for mt in mod_totals.values()), 2)
        g_crc = sum(mt["credit_cnt"] for mt in mod_totals.values())
        g_cra = round(sum(mt["credit_amt"] for mt in mod_totals.values()), 2)
        g_zc = sum(mt["zero_cnt"] for mt in mod_totals.values())
        w.writerow(["GRAND TOTAL (15-26 Nov)", "ALL MODULES", g_cc, f"{g_ca:.2f}", g_crc, f"{g_cra:.2f}", g_zc, g_cc + g_crc, f"{round(g_ca + g_cra, 2):.2f}"])

    # =========================================================================
    # CSV 4: BRIEF EXECUTIVE DAILY SUMMARY
    # =========================================================================
    exec_csv_path = os.path.join(OUTPUT_DIR, "HMS_Brief_Executive_Summary_15_to_26_Nov_2026.csv")
    exec_headers = [
        "Date (IST)",
        "Total Shifts", "Active Shifts", "Closed Shifts",
        "Shift Stored Cash (Rs)", "Shift Stored Credit/Card (Rs)", "Shift Stored Return (Rs)", "Shift Stored Closing (Rs)",
        "Calc Module Cash (Rs)", "Calc Module Credit/Card (Rs)", "Calc Module Expenses (Rs)", "Calc Module Returns (Rs)",
        "Date Ledger Gross Cash (Rs)", "Date Ledger Card/UPI/Bank (Rs)", "Date Ledger Credit/Scheme (Rs)", "Date Ledger Total Collection (Rs)",
        "Counter Paid Discount (Rs)", "All Billed Discount (Rs)", "Gross Total Before Discount (Rs)",
        "Date Ledger Expenses (Rs)", "Date Ledger Returns/Refunds (Rs)", "Date Ledger Net Cash Handover (Rs)",
        "Cash Pending Bills Count", "Cash Pending Bills Amount (Rs)",
        "Credit/Ins Pending Bills Count", "Credit/Ins Pending Bills Amount (Rs)",
        "Zero-Fee Pending Count",
    ]
    with open(exec_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(exec_headers)
        for er in exec_rows:
            w.writerow([
                er["date"], er["total_shifts"], er["active_shifts"], er["closed_shifts"],
                f"{er['stored_cash']:.2f}", f"{er['stored_credit']:.2f}", f"{er['stored_return']:.2f}", f"{er['stored_closing']:.2f}",
                f"{er['calc_cash']:.2f}", f"{er['calc_credit']:.2f}", f"{er['calc_exp']:.2f}", f"{er['calc_ret']:.2f}",
                f"{er['led_gross_cash']:.2f}", f"{er['led_card_bank']:.2f}", f"{er['led_credit_scheme']:.2f}", f"{er['led_total']:.2f}",
                f"{er['paid_disc_total']:.2f}", f"{er['all_disc_total']:.2f}", f"{er['gross_before_disc']:.2f}",
                f"{er['led_exp']:.2f}", f"{er['led_ret']:.2f}", f"{er['led_net']:.2f}",
                er["p_cash_c"], f"{er['p_cash_a']:.2f}", er["p_cred_c"], f"{er['p_cred_a']:.2f}", er["p_zero_c"],
            ])
        w.writerow([
            "GRAND TOTAL",
            sum(r["total_shifts"] for r in exec_rows), sum(r["active_shifts"] for r in exec_rows), sum(r["closed_shifts"] for r in exec_rows),
            f"{gt_st_cash:.2f}", f"{gt_st_cred:.2f}", f"{sum(r['stored_return'] for r in exec_rows):.2f}", f"{sum(r['stored_closing'] for r in exec_rows):.2f}",
            f"{sum(r['calc_cash'] for r in exec_rows):.2f}", f"{sum(r['calc_credit'] for r in exec_rows):.2f}", f"{sum(r['calc_exp'] for r in exec_rows):.2f}", f"{sum(r['calc_ret'] for r in exec_rows):.2f}",
            f"{gt_led_cash:.2f}", f"{gt_led_card:.2f}", f"{gt_led_cr:.2f}", f"{gt_led_tot:.2f}",
            f"{gt_pd_tot:.2f}", f"{gt_ad_tot:.2f}", f"{gt_gross:.2f}",
            f"{gt_exp:.2f}", f"{gt_ret:.2f}", f"{gt_net:.2f}",
            sum(r["p_cash_c"] for r in exec_rows), f"{sum(r['p_cash_a'] for r in exec_rows):.2f}",
            sum(r["p_cred_c"] for r in exec_rows), f"{sum(r['p_cred_a'] for r in exec_rows):.2f}",
            sum(r["p_zero_c"] for r in exec_rows),
        ])

    print("=== GENERATED CSV FILES ===")
    for p in (cc_report_path, exec_csv_path, shift_csv_path, pending_csv_path):
        print(" -", p)

    print("\n=== CASH COUNTER GRAND SUMMARY (15 NOV - 26 NOV 2026 IST) ===")
    print(f"Shifts: {len(shift_rows)} (Active: {sum(r['active_shifts'] for r in exec_rows)}, Closed: {sum(r['closed_shifts'] for r in exec_rows)})")
    print(f"Shift Stored        -> Cash: {gt_st_cash:.2f} | Credit/Card: {gt_st_cred:.2f} | Stored Total: {(gt_st_cash+gt_st_cred):.2f} | Returns: {sum(r['stored_return'] for r in exec_rows):.2f} | Closing: {sum(r['stored_closing'] for r in exec_rows):.2f}")
    print(f"Ledger Collected    -> Gross Cash: {gt_led_cash:.2f} | Card/UPI/Bank: {gt_led_card:.2f} | Credit/Scheme: {gt_led_cr:.2f} | Total Credit(Non-Cash): {gt_led_nc:.2f} | Net Collection: {gt_led_tot:.2f}")
    print(f"Discounts           -> Counter Paid: {gt_pd_tot:.2f} (Pharm={gt_pd_ph:.2f}, Invest={gt_pd_inv:.2f}, Disch={gt_pd_dis:.2f}) | All Billed: {gt_ad_tot:.2f}")
    print(f"Gross Before Disc   -> {gt_gross:.2f}")
    print(f"Deductions & Net    -> Expenses: {gt_exp:.2f} | Returns/Refunds: {gt_ret:.2f} | Net Cash Handover: {gt_net:.2f}")

    print("\n=== DAILY BREAKDOWN (15-26 NOV) ===")
    for er in exec_rows:
        print(f"  {er['date']} | Sh={er['total_shifts']:2d} | StCash={er['stored_cash']:10.2f} StCr={er['stored_credit']:10.2f} | LedCash={er['led_gross_cash']:10.2f} Card={er['led_card_bank']:10.2f} CrSch={er['led_credit_scheme']:8.2f} | PaidDisc={er['paid_disc_total']:8.2f} | NetColl={er['led_total']:10.2f} | Exp={er['led_exp']:8.2f} Ret={er['led_ret']:8.2f} NetHand={er['led_net']:10.2f}")

    print("\n=== OUTLET BREAKDOWN (15-26 NOV) ===")
    for oc in outlets_seen:
        o_shifts = [r for r in shift_rows if r["outlet_code"] == oc]
        o_lm = summarize_ledger_bills(ledger_bills_by_outlet.get(oc, []), rp_by_outlet.get(oc, []))
        o_disc = disc_by_outlet.get(oc, {"paid_total": 0.0, "all_total": 0.0})
        if not o_shifts and o_lm["total_collection"] == 0 and o_disc["all_total"] == 0:
            continue
        print(f"  {oc:8s} ({outlet_map.get(oc, oc):15s}) | Sh={len(o_shifts):3d} | StCash={sum(r['stored_cash'] for r in o_shifts):10.2f} StCr={sum(r['stored_credit'] for r in o_shifts):10.2f} | LedCash={o_lm['gross_cash']:10.2f} Card={o_lm['card_bank']:10.2f} Cr={o_lm['credit_scheme']:8.2f} NetColl={o_lm['total_collection']:10.2f} | PaidDisc={o_disc['paid_total']:8.2f} AllDisc={o_disc['all_total']:8.2f} | Exp={o_lm['expenses']:8.2f} Ret={o_lm['returns_refunds']:9.2f} NetHand={o_lm['net_handover']:10.2f}")

    client.close()


if __name__ == "__main__":
    main()
