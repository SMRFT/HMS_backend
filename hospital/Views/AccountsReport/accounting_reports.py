from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.http import JsonResponse
from datetime import datetime, date
import os
import json as _json
from pymongo import MongoClient
from pyauth.auth import HasRoleAndDataPermission
from decimal import Decimal
from bson.decimal128 import Decimal128
from ...models import Cashcountershiftdetails, DischargeBilling, Admission, Patient, ReceiptAndPayment, Billing, PharmacyBilling, SalesReturn, PharmacyItem, PharmacyStock

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(v):
    try:
        from bson import Decimal128
        if v is None: return 0.0
        if isinstance(v, Decimal128): return float(v.to_decimal())
        if isinstance(v, Decimal): return float(v)
        if isinstance(v, str): return float(v.replace(',', ''))
        return float(v)
    except:
        return 0.0

def _parse_json(val):
    if not val: return []
    if isinstance(val, list): return val
    if isinstance(val, str):
        try: return _json.loads(val)
        except: return []
    return []

def _format_description(desc):
    if not desc:
        return ""
    if isinstance(desc, str):
        desc_str = desc.strip()
        if desc_str.startswith('{') and desc_str.endswith('}'):
            try:
                import ast
                parsed = ast.literal_eval(desc_str)
                if isinstance(parsed, dict):
                    desc = parsed
            except Exception:
                try:
                    desc = _json.loads(desc_str)
                except Exception:
                    pass
    if isinstance(desc, dict):
        parts = []
        for k, v in desc.items():
            if v is not None and str(v).strip() != "":
                clean_k = str(k).replace('_', ' ').title()
                if clean_k.lower() == "description":
                    parts.append(str(v))
                else:
                    parts.append(f"{clean_k}: {v}")
        return " | ".join(parts)
    if isinstance(desc, list):
        return "; ".join(_format_description(item) for item in desc if item)
    return str(desc)

def _format_dt(val):
    if not val: return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return str(val)

def _format_time(val):
    if not val: return ""
    dt_obj = val
    if isinstance(val, str):
        try:
            # Handle "2026-05-11 10:00:00" or ISO
            if " " in val:
                dt_obj = datetime.strptime(val.split('.')[0], "%Y-%m-%d %H:%M:%S")
            else:
                dt_obj = datetime.fromisoformat(val.replace('Z', '+00:00'))
        except:
            return str(val)
    
    if hasattr(dt_obj, 'strftime'):
        return dt_obj.strftime("%I.%M%p").lower()
    return str(val)

def _auth_scope(request):
    """hospital_code/branch_code as sent by every existing report in this file."""
    hospital_code = (
        request.GET.get("auth-hospital-code") or
        request.META.get("HTTP_AUTH_HOSPITAL_CODE") or
        request.META.get("HTTP_HOSPITAL_CODE") or
        (request.headers.get("hospital-code") if hasattr(request, "headers") else None)
    )
    branch_code = (
        request.GET.get("auth-branch-code") or
        request.META.get("HTTP_AUTH_BRANCH_CODE") or
        request.META.get("HTTP_BRANCH_CODE") or
        (request.headers.get("branch-code") if hasattr(request, "headers") else None)
    )
    return hospital_code, branch_code

def _date_range_query(from_f, to_f, field="created_date"):
    q = {}
    if from_f:
        f_date = _parse_date(from_f)
        if f_date:
            q.setdefault(field, {})["$gte"] = datetime.combine(f_date, datetime.min.time())
    if to_f:
        t_date = _parse_date(to_f)
        if t_date:
            q.setdefault(field, {})["$lte"] = datetime.combine(t_date, datetime.max.time())
    return q

def _card_amount(payment_mode, payment_details):
    """
    Returns the Card portion of a payment: the full amount if the payment
    mode IS Card, or just the card slice of a 'Multiple Payment' breakdown.
    Returns None if there's no card component at all.
    """
    mode = (payment_mode or "").strip().lower()
    if mode == "card":
        return _to_float((payment_details or {}).get("Paid_amount"))
    if mode == "multiple payment":
        breakdown = (payment_details or {}).get("breakdown") or []
        card_total = sum(
            _to_float(b.get("Paid_amount"))
            for b in breakdown if isinstance(b, dict) and (b.get("method") or "").strip().lower() == "card"
        )
        return card_total if card_total > 0 else None
    return None

def _parse_date(val):
    if not val: return None
    if isinstance(val, datetime): return val.date()
    if isinstance(val, date): return val
    if isinstance(val, str):
        val = val.strip()
        if not val: return None
        try:
            return date.fromisoformat(val[:10])
        except:
            pass
        try:
            return datetime.strptime(val.split(' ')[0], "%Y-%m-%d").date()
        except:
            pass
        try:
            return datetime.strptime(val.split(' ')[0], "%d/%m/%Y").date()
        except:
            pass
        try:
            return datetime.strptime(val.split(' ')[0], "%d-%m-%Y").date()
        except:
            pass
    return None

# ─────────────────────────────────────────────────────────────────────────────
# Cashier Wise Reports
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Centralized Detail Fetcher
# ─────────────────────────────────────────────────────────────────────────────

def fetch_detailed_billing_data(db, ccc_records):
    """
    Enriches a list of hospital_cashcountercollection records with their corresponding 
    detailed billing fields from underlying collections.
    """
    if not ccc_records:
        return []
        
    enriched_data = []
    
    # Fetch all bill types for mapping
    billtype_map = {}
    billtype_id_map = {}
    try:
        bt_list = list(db["hospital_billtype"].find({}, {"billTypeNo": 1, "bill_name": 1, "bill_type": 1}))
        for bt in bt_list:
            bt_no = bt.get("billTypeNo")
            bt_name = bt.get("bill_name")
            bt_id = bt.get("bill_type")
            if bt_no and bt_name:
                billtype_map[str(bt_no).strip()] = str(bt_name).strip()
            if bt_id is not None and bt_name:
                billtype_id_map[str(bt_id).strip()] = str(bt_name).strip()
    except Exception as e:
        print("Error fetching bill types:", e)
    
    # Pre-group bill_numbers by billing_category for bulk queries
    by_category = {}
    for r in ccc_records:
        cat = r.get("billing_category")
        if not cat:
            continue
        by_category.setdefault(cat, []).append(r)
        
    # Bulk fetch helper for collections
    def fetch_docs(collection_name, field_name, bill_numbers):
        if not bill_numbers:
            return {}
        docs = list(db[collection_name].find({field_name: {"$in": bill_numbers}}))
        return {str(d[field_name]): d for d in docs if field_name in d}

    # Helper to get bill numbers
    def get_bill_nums(records):
        nums = []
        for r in records:
            b_no = r.get("bill_no") or r.get("bill_number")
            if b_no:
                nums.append(str(b_no))
        return list(set(nums))

    # 1. OPPharmacyBills -> hospital_pharmacybilling (bill_no)
    pharmacy_bills = by_category.get("OPPharmacyBills", []) + by_category.get("Pharmacy", []) + by_category.get("PharmacyBills", [])
    pharmacy_nums = get_bill_nums(pharmacy_bills)
    pharmacy_map = fetch_docs("hospital_pharmacybilling", "bill_no", pharmacy_nums)

    # 2. Investigation -> hospital_investbilling (investBillNo)
    invest_bills = by_category.get("Investigation", []) + by_category.get("InvestigationBills", [])
    invest_nums = get_bill_nums(invest_bills)
    invest_map = fetch_docs("hospital_investbilling", "investBillNo", invest_nums)

    # 3. Billing -> hospital_billing (bill_number)
    billing_bills = by_category.get("Billing", []) + by_category.get("Registration", []) + by_category.get("RegistrationBills", [])
    billing_nums = get_bill_nums(billing_bills)
    billing_map = fetch_docs("hospital_billing", "bill_number", billing_nums)

    # 4. Discharge -> hospital_dischargebilling (bill_no)
    discharge_bills = by_category.get("Discharge", []) + by_category.get("DischargeBills", [])
    discharge_nums = get_bill_nums(discharge_bills)
    discharge_map = fetch_docs("hospital_dischargebilling", "bill_no", discharge_nums)

    # 5. IPAdvance -> hospital_admission (advance_payments.bill_no)
    advance_bills = by_category.get("IPAdvance", []) + by_category.get("IPAdvanceBills", []) + by_category.get("IPAdvance Payment", []) + by_category.get("Advance", [])
    advance_nums = get_bill_nums(advance_bills)
    advance_map = {}
    if advance_nums:
        adms = list(db["hospital_admission"].find({"advance_payments.bill_no": {"$in": advance_nums}}))
        for adm in adms:
            pays = adm.get("advance_payments", [])
            for p in pays:
                if isinstance(p, dict):
                    b_no = str(p.get("bill_no"))
                    if b_no in advance_nums:
                        advance_map[b_no] = {
                            "admission": adm,
                            "payment": p
                        }

    # 6. Sales Return -> hospital_salesreturn (return_bill_no)
    sales_return_bills = by_category.get("Sales Return", []) + by_category.get("sales_return", [])
    sales_return_nums = get_bill_nums(sales_return_bills)
    sales_return_map = fetch_docs("hospital_salesreturn", "return_bill_no", sales_return_nums)

    # 7. Receipt / Payment -> hospital_receiptandpayment (voucher_no)
    rp_bills = by_category.get("Receipt", []) + by_category.get("Payment", [])
    rp_nums = get_bill_nums(rp_bills)
    rp_map = fetch_docs("hospital_receiptandpayment", "voucher_no", rp_nums)

    # Loop through each ccc record and enrich it
    for r in ccc_records:
        cat = r.get("billing_category")
        bill_no = str(r.get("bill_no") or r.get("bill_number") or "")
        
        # Default empty details
        detail = {
            "type": cat,
            "type_name": cat,
            "bill_no": bill_no,
            "bill_date": _format_dt(r.get("created_date")),
            "uhid": "",
            "patient_name": "",
            "net_amount": _to_float(r.get("collected_amount")),
            "display_amount": _to_float(r.get("collected_amount")) - _to_float(r.get("Returned_amount")),
            "payment_mode": "Cash",
            "cashier_id": r.get("created_by"),
            "outlet_code": r.get("outlet_code"),
            "shiftno": r.get("shift_no"),
            "status": r.get("transaction_type") or "Paid",
            "items": []
        }
        
        # Override with detailed information depending on category
        if cat in ["OPPharmacyBills", "Pharmacy", "PharmacyBills"] and bill_no in pharmacy_map:
            d = pharmacy_map[bill_no]
            is_ip = bool(d.get("inpatient_number") or d.get("ip_no") or d.get("admission_id"))
            p_mode = d.get("payment_mode") or d.get("payment_method") or "Cash"
            detail.update({
                "type": "Pharmacy",
                "type_name": "PHARMACY IP BILL (SH)" if is_ip else "PHARMACY OP BILL (SH)",
                "uhid": d.get("uhid"),
                "net_amount": _to_float(d.get("net_amount")),
                "display_amount": _to_float(d.get("net_amount")),
                "payment_mode": p_mode,
                "payment_details": d.get("payment_details") or {},
                "items": d.get("items") or d.get("medicine_particulars") or []
            })
            
        elif cat in ["Investigation", "InvestigationBills"] and bill_no in invest_map:
            d = invest_map[bill_no]
            
            # Lookup detailed name from bill type
            bt_no = d.get("billTypeNo")
            bt_name = billtype_map.get(bt_no) if bt_no else None
            if not bt_name and d.get("item"):
                first_item = d.get("item")[0]
                bt_no = first_item.get("billTypeNo")
                bt_name = billtype_map.get(bt_no) if bt_no else None
            
            display_type = bt_name or "Investigation"
            if "(SH)" not in display_type:
                display_type = f"{display_type} (SH)"
            
            detail.update({
                "type": "Investigation",
                "type_name": display_type,
                "uhid": d.get("uhid"),
                "net_amount": _to_float(d.get("finalPrice") or d.get("total")),
                "display_amount": _to_float(d.get("finalPrice") or d.get("total")),
                "payment_mode": d.get("paymentMethod") or d.get("payment_method") or "Cash",
                "payment_details": d.get("payment_details") or {},
                "items": d.get("item") or []
            })
            
        elif cat in ["Billing", "Registration", "RegistrationBills"] and bill_no in billing_map:
            d = billing_map[bill_no]
            detail.update({
                "type": "Registration",
                "type_name": "REGISTRATION(SH)",
                "uhid": d.get("uhid"),
                "net_amount": _to_float(d.get("total_fees")),
                "display_amount": _to_float(d.get("total_fees")),
                "payment_mode": d.get("payment_mode") or d.get("payment_method") or "Cash",
                "payment_details": d.get("payment_details") or {},
                "items": d.get("items") or []
            })
            
        elif cat in ["Discharge", "DischargeBills"] and bill_no in discharge_map:
            d = discharge_map[bill_no]
            pd = d.get("payment_details") or {}
            p_mode = pd.get("method") or d.get("payment_mode") or d.get("payment_method") or "Cash"
            detail.update({
                "type": "Discharge",
                "type_name": "DISCHARGE",
                "uhid": d.get("uhid"),
                "net_amount": _to_float(d.get("net_amount") or d.get("paid_amount")),
                "display_amount": _to_float(d.get("net_amount") or d.get("paid_amount")),
                "payment_mode": p_mode,
                "payment_details": pd,
                "items": d.get("items") or []
            })
            
        elif cat in ["IPAdvance", "IPAdvanceBills", "Advance"] and bill_no in advance_map:
            d = advance_map[bill_no]
            adm = d["admission"]
            pay = d["payment"]
            pd = pay.get("payment_details") or {}
            p_mode = pd.get("method") or pay.get("payment_mode") or "Cash"
            detail.update({
                "type": "IPAdvance",
                "type_name": "ADVANCE",
                "uhid": adm.get("uhid"),
                "net_amount": _to_float(pay.get("amount")),
                "display_amount": _to_float(pay.get("amount")),
                "payment_mode": p_mode,
                "payment_details": pd,
                "items": []
            })
            
        elif cat in ["Sales Return", "sales_return"] and bill_no in sales_return_map:
            d = sales_return_map[bill_no]
            meds = d.get("medicine_particulars", [])
            if isinstance(meds, str):
                try: meds = _json.loads(meds)
                except: meds = []
            amt = 0.0
            for m in meds:
                qty = float(m.get("return_qty", 0))
                price = float(m.get("price", 0))
                amt += qty * price
            
            detail.update({
                "type": "Sales Return",
                "type_name": "SALES RETURNS",
                "uhid": d.get("uhid"),
                "net_amount": amt,
                "display_amount": -amt,
                "payment_mode": "Cash",
                "items": meds
            })
            
        elif cat in ["Receipt", "Payment"] and bill_no in rp_map:
            d = rp_map[bill_no]
            amt = _to_float(d.get("amount"))
            detail.update({
                "type": cat,
                "type_name": "MISCELLANEOUS INCOME" if cat == "Receipt" else cat,
                "net_amount": amt,
                "display_amount": -amt if cat == "Payment" else amt,
                "payment_mode": "Cash",
                "items": d.get("description") or []
            })
            
        elif cat in ["remitted", "submit"]:
            detail.update({
                "type": "Remitted" if cat == "remitted" else "Submitted",
                "type_name": "REMITTED TO BANK" if cat == "remitted" else "SUBMITTED TO ACCOUNT",
                "net_amount": _to_float(r.get("collected_amount")),
                "display_amount": -_to_float(r.get("collected_amount")) if cat == "remitted" else _to_float(r.get("collected_amount")),
                "payment_mode": "Cash",
                "items": []
            })
            
        enriched_data.append(detail)
        
    return enriched_data

# ─────────────────────────────────────────────────────────────────────────────
# Cashier Wise Reports
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def get_shift_summary_report(request):
    """
    Returns shift summary for cashier wise reports.
    Uses hospital_cashcountercollection for shift calculations.
    """
    try:
        data = request.data
        from_date = data.get("from_date")
        to_date = data.get("to_date")
        hospital_code = (
            data.get("auth-hospital-code") or 
            request.META.get("HTTP_AUTH_HOSPITAL_CODE") or 
            request.META.get("HTTP_HOSPITAL_CODE") or 
            (request.headers.get("hospital-code") if hasattr(request, "headers") else None)
        )
        branch_code = (
            data.get("auth-branch-code") or 
            request.META.get("HTTP_AUTH_BRANCH_CODE") or 
            request.META.get("HTTP_BRANCH_CODE") or 
            (request.headers.get("branch-code") if hasattr(request, "headers") else None)
        )
        
        queryset = Cashcountershiftdetails.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        )
        if from_date:
            queryset = queryset.filter(date__gte=from_date)
        if to_date:
            queryset = queryset.filter(date__lte=to_date)
            
        shifts = queryset.order_by("-date", "-StartingTime")
        cashier_ids = list(set([s.CashierID for s in shifts]))
        shift_nos = [s.shiftno for s in shifts]
        
        cashier_name_map = {}
        try:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            db = client['Global']
            profiles = list(db['backend_diagnostics_profile'].find(
                {"employeeId": {"$in": cashier_ids}},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            ))
            cashier_name_map = {p['employeeId']: p['employeeName'] for p in profiles}
            client.close()
        except:
            pass
            
        # Bulk query hospital_cashcountercollection for all shifts
        shift_totals = {}
        try:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            db = client["HMS"]
            ccc_docs = list(db["hospital_cashcountercollection"].find({"shift_no": {"$in": shift_nos}}))
            for doc in ccc_docs:
                s_no = doc.get("shift_no")
                if not s_no: continue
                shift_totals.setdefault(s_no, {"collected": 0.0, "returns": 0.0, "remitted": 0.0, "submitted": 0.0})
                
                cat = doc.get("billing_category", "").lower()
                tx_type = doc.get("transaction_type", "").lower()
                col_amt = _to_float(doc.get("collected_amount"))
                ret_amt = _to_float(doc.get("Returned_amount"))
                
                if "return" in cat or tx_type == "payment" or tx_type == "returned":
                    shift_totals[s_no]["returns"] += col_amt or ret_amt
                elif cat == "remitted" or tx_type == "remitted":
                    shift_totals[s_no]["remitted"] += col_amt
                elif cat == "submit" or tx_type == "submit":
                    shift_totals[s_no]["submitted"] += col_amt
                else:
                    shift_totals[s_no]["collected"] += col_amt
            client.close()
        except Exception as e:
            print("Error querying cash counter collection for shift totals:", e)

        report_data = []
        for s in shifts:
            st = shift_totals.get(s.shiftno, {})
            collected = st.get("collected", _to_float(s.collected_Amount))
            returns = st.get("returns", _to_float(s.SalesReturnAmount))
            remitted = st.get("remitted", _to_float(s.RemittedToBank))
            submitted = st.get("submitted", _to_float(s.SubmittedToAccount))
            
            report_data.append({
                "shiftno": s.shiftno,
                "CashierID": s.CashierID,
                "User": cashier_name_map.get(s.CashierID, s.CashierID),
                "CashCounter": s.CashCounter,
                "OpeningBalance": _to_float(s.OpeningBalance),
                "ClosingBalance": _to_float(s.ClosingBalance),
                "collected_Amount": round(collected - returns, 2),
                "PettyCashBalance": _to_float(s.PettyCashBalance),
                "RemittedToBank": round(remitted, 2),
                "HandOverAmount": _to_float(s.HandOverAmount),
                "SalesReturnAmount": round(returns, 2),
                "ShiftStatus": s.ShiftStatus,
                "StartingTime": _format_dt(s.StartingTime),
                "StartTime": _format_time(s.StartingTime),
                "closingTime": _format_dt(s.closingTime),
                "EndTime": _format_time(s.closingTime),
                "date": str(s.date),
                "outlet_code": s.outlet_code,
            })
            
        return Response({
            "success": True,
            "data": report_data
        })
    except Exception as e:
        import traceback
        print("Shift Summary Error:", str(e))
        print(traceback.format_exc())
        return Response({"success": False, "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# Discharge Bills Report
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def discharge_bills_report(request):
    """
    Dedicated reporting API for discharge bills.
    Queries hospital_dischargebilling directly.

    Extra query params:
    - status: 'Billed' (default) | 'Estimate' | 'all'
    - from_date: YYYY-MM-DD
    - to_date: YYYY-MM-DD
    - payment_mode: 'Cash' | 'Card' | 'Cheque' | 'Multiple Payment' (omit or 'all' = all)
    - insurance: 'true' -> only insurance-linked patients, 'false' -> only non-insurance
    - discount_only: 'true' -> only bills where a discount was actually applied
    """
    try:
        status_f = request.GET.get("status", "Billed")
        from_f   = request.GET.get("from_date")
        to_f     = request.GET.get("to_date")
        payment_mode_f = (request.GET.get("payment_mode") or "").strip()
        insurance_f    = request.GET.get("insurance")
        discount_only  = request.GET.get("discount_only") == "true"
        outlet_f       = request.GET.get("outlet_code") or request.GET.get("outlet")

        hospital_code, branch_code = _auth_scope(request)

        # Connect MongoDB
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        mongo_q = {
            "is_cancelled": {"$ne": True}
        }
        if status_f and status_f.lower() != "all":
            mongo_q["status"] = status_f
        if hospital_code:
            mongo_q["hospital_code"] = hospital_code
        if branch_code:
            mongo_q["branch_code"] = branch_code

        discharge_docs = list(db["hospital_dischargebilling"].find(mongo_q))

        # Bulk lookup insurance providers from hospital_insuranceprovider
        ins_docs = list(db["hospital_insuranceprovider"].find({}, {"company_code": 1, "company_name": 1}))
        insurance_code_to_name = {str(ins.get("company_code")).strip(): str(ins.get("company_name", "")).strip() for ins in ins_docs if ins.get("company_code")}
        insurance_name_to_code = {str(ins.get("company_name", "")).strip().lower(): str(ins.get("company_code")).strip() for ins in ins_docs if ins.get("company_name")}

        # Date range filtering
        f_d = _parse_date(from_f) if from_f else None
        t_d = _parse_date(to_f) if to_f else None

        records = []
        for doc in discharge_docs:
            b_date = _parse_date(doc.get("bill_date")) or _parse_date(doc.get("created_date"))
            if f_d and b_date and b_date < f_d:
                continue
            if t_d and b_date and b_date > t_d:
                continue
            records.append(doc)

        bill_nos = [d.get("bill_no") for d in records if d.get("bill_no")]
        ccc_map = {}
        if bill_nos:
            ccc_docs = list(db["hospital_cashcountercollection"].find({
                "bill_number": {"$in": bill_nos}
            }))
            for c in ccc_docs:
                b_num = c.get("bill_number")
                if b_num and b_num not in ccc_map:
                    ccc_map[b_num] = c

        # Admission lookup for room, admission date, insurance
        ip_numbers = list(set([d.get("ip_number") for d in records if d.get("ip_number")]))
        admission_map = {}
        if ip_numbers:
            for a in db["hospital_admission"].find({"$or": [{"ipNumber": {"$in": ip_numbers}}, {"ip_number": {"$in": ip_numbers}}]}):
                ip_k = a.get("ipNumber") or a.get("ip_number") or a.get("ip_no")
                if ip_k:
                    admission_map[ip_k] = a

        # Patient lookup
        uhids = list(set([d.get("uhid") for d in records if d.get("uhid")]))
        patient_map = {}
        if uhids:
            try:
                for p in Patient.objects.filter(uhid__in=uhids):
                    patient_map[p.uhid] = p
            except Exception as e:
                print("Patient lookup error:", e)

        client.close()

        filtered = []

        for doc in records:
            bill_no = doc.get("bill_no")
            uhid = doc.get("uhid")
            ip_number = doc.get("ip_number")

            payment_mode = (
                (doc.get("payment_details") or {}).get("method")
                or ccc_map.get(bill_no, {}).get("payment_mode")
                or doc.get("payment_mode")
                or "Cash"
            )
            if payment_mode_f and payment_mode_f.lower() != "all" and payment_mode.lower() != payment_mode_f.lower():
                continue

            disc_amt = _to_float(doc.get("discount_amount") or doc.get("total_disc") or 0)
            has_discount = disc_amt > 0
            if discount_only and not has_discount:
                continue

            adm = admission_map.get(ip_number, {})
            p = patient_map.get(uhid)

            comp_code = str(adm.get("company_code") or adm.get("companyCode") or (p.company_code if p else "") or "").strip()
            adm_ins_name = adm.get("insuranceCompanyName") or adm.get("company_name") or adm.get("insurance_company")
            
            if not comp_code and adm_ins_name:
                comp_code = insurance_name_to_code.get(str(adm_ins_name).strip().lower(), "")

            comp_name = (
                adm_ins_name or 
                insurance_code_to_name.get(comp_code) or 
                (comp_code if comp_code and not comp_code.isdigit() else None)
            )

            has_insurance = bool(
                comp_name or
                comp_code or
                (p and (getattr(p, 'customer_type', '') or '').lower() == 'insurance')
            )
            if insurance_f == "true" and not has_insurance:
                continue
            if insurance_f == "false" and has_insurance:
                continue

            final_company_name = comp_name or (insurance_code_to_name.get(comp_code) if comp_code else None) or (f"Company #{comp_code}" if comp_code else "GENERAL / PRIVATE")

            # Build patient details
            p_name = ""
            if p:
                p_name = f"{p.firstName or ''} {p.lastName or ''}".strip()
                patient_details = {
                    "patient_name": p_name,
                    "age": p.age,
                    "gender": p.gender,
                }
            else:
                p_name = adm.get("patient_name") or adm.get("patientname") or doc.get("patient_name") or "N/A"
                patient_details = {
                    "patient_name": p_name,
                    "age": adm.get("age"),
                    "gender": adm.get("gender"),
                }

            room_details = adm.get("room_details") or []
            active_rooms = [rm for rm in room_details if rm.get("is_roomActive") in (True, "True", "true", 1, "1")]
            room_no = (active_rooms[-1] if active_rooms else (room_details[-1] if room_details else {})).get("roomNo") or (active_rooms[-1] if active_rooms else (room_details[-1] if room_details else {})).get("roomNumber") or "N/A"
            patient_details["room_no"] = room_no
            patient_details["admission_date"] = _format_dt(adm.get("admissionDateTime") or adm.get("created_date"))

            # Department-wise drill-down from line items
            items = doc.get("items") or []
            if isinstance(items, str):
                items = _parse_json(items)
            dept_totals = {}
            for it in items:
                if not isinstance(it, dict): continue
                cat = it.get("category") or it.get("package_name") or it.get("item_description") or "Other"
                dept_totals[cat] = dept_totals.get(cat, 0) + _to_float(it.get("amount"))
            department_breakdown = [{"category": k, "amount": v} for k, v in dept_totals.items()]

            b_date_val = doc.get("bill_date") or doc.get("created_date")
            b_date_str = None
            if isinstance(b_date_val, (datetime, date)):
                b_date_str = b_date_val.isoformat()
            elif isinstance(b_date_val, str):
                b_date_str = b_date_val

            cashier_id = ccc_map.get(bill_no, {}).get("created_by") or doc.get("CashierID") or doc.get("created_by") or ""

            filtered.append({
                "id": doc.get("discharge_id"),
                "bill_no": bill_no,
                "bill_id": bill_no,
                "sh_bill_no": doc.get("sh_bill_no") or doc.get("estimate_number") or doc.get("sh_bill_number") or bill_no,
                "estimate_number": doc.get("estimate_number"),
                "uhid": uhid,
                "ip_number": ip_number,
                "branch_code": doc.get("branch_code"),
                "hospital_code": doc.get("hospital_code"),
                "bill_date": b_date_str,
                "admitting_date": patient_details.get("admission_date"),
                "discharge_date": b_date_str,
                "total_amount": _to_float(doc.get("total_amount")),
                "bill_amount": _to_float(doc.get("total_amount") or doc.get("net_amount")),
                "advance_amount": _to_float(doc.get("advance_amount")),
                "advance": _to_float(doc.get("advance_amount")),
                "net_amount": _to_float(doc.get("net_amount")),
                "card_number": adm.get("policy_no") or adm.get("insurance_card_no") or adm.get("card_number") or doc.get("card_number") or "",
                "service_no": adm.get("service_no") or adm.get("serviceNo") or doc.get("service_no") or "",
                "claim_reference": adm.get("claim_reference") or adm.get("claim_id") or doc.get("claim_reference") or "",
                "place": adm.get("place") or doc.get("place") or "",
                "despatch_date": doc.get("despatch_date") or "",
                "settlement_date": doc.get("settlement_date") or "",
                "settled_amount": _to_float(doc.get("settled_amount")),
                "tds": _to_float(doc.get("tds")),
                "bank": doc.get("bank") or "",
                "paid_by_patient": _to_float(doc.get("paid_by_patient") or doc.get("paid_amount")),
                "disallowed_amount": _to_float(doc.get("disallowed_amount")),
                "due": _to_float(doc.get("due") or doc.get("due_amount") or doc.get("net_amount")),
                "settlement_duration": doc.get("settlement_duration") or "",
                "old_billno": doc.get("old_billno") or "",
                "total_disc": disc_amt,
                "discount_amount": disc_amt,
                "discount_percent": _to_float(doc.get("discount_percent") or 0),
                "has_discount": has_discount,
                "cashier_id": cashier_id,
                "user": str(cashier_id).upper(),
                "status": doc.get("status") or "NOT BILLED",
                "patient_details": patient_details,
                "patient_name": p_name,
                "payment_mode": payment_mode,
                "has_insurance": has_insurance,
                "company_code": comp_code,
                "company_name": final_company_name,
                "insurance_company": final_company_name,
                "department_breakdown": department_breakdown,
            })

        filtered.sort(key=lambda x: x["bill_date"] or "", reverse=True)
        return Response({"success": True, "data": filtered})
    except Exception as e:
        import traceback
        print("Discharge Bills Report Error:", str(e))
        print(traceback.format_exc())
        return Response({"success": False, "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def advance_registration_report(request):
    """
    Dedicated reporting API for IP advance payments.
    Queries all active admissions directly and matches all advance payment records.
    """
    try:
        from_f = request.GET.get("from_date")
        to_f   = request.GET.get("to_date")
        outlet_f = request.GET.get("outlet_code") or request.GET.get("outlet")
        is_insurance = request.GET.get("insurance") == "true"
        
        hospital_code, branch_code = _auth_scope(request)
        
        # Connect MongoDB
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]
        
        adm_query = {
            "is_cancelled": {"$ne": True},
            "advance_payments": {"$exists": True, "$ne": []}
        }
        if hospital_code:
            adm_query["hospital_code"] = hospital_code
        if branch_code:
            adm_query["branch_code"] = branch_code
            
        admissions = list(db["hospital_admission"].find(adm_query))
        
        # Bulk lookup insurance providers from hospital_insuranceprovider
        ins_docs = list(db["hospital_insuranceprovider"].find({}, {"company_code": 1, "company_name": 1}))
        insurance_code_to_name = {str(ins.get("company_code")).strip(): str(ins.get("company_name", "")).strip() for ins in ins_docs if ins.get("company_code")}

        # Also query cashcountercollection for cashier mapping if available
        ccc_map = {}
        try:
            ccc_docs = list(db["hospital_cashcountercollection"].find({
                "billing_category": {"$in": ["IPAdvance", "IPAdvanceBills", "IPAdvance Payment", "advance", "Advance", "CentralCashCounter"]}
            }))
            for c in ccc_docs:
                b_num = c.get("bill_number") or c.get("bill_no")
                if b_num and b_num not in ccc_map:
                    ccc_map[b_num] = c
        except Exception:
            pass

        # Cashier names lookup from Global DB
        cashier_name_map = {}
        try:
            g_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            g_db = g_client['Global']
            profiles = list(g_db['backend_diagnostics_profile'].find(
                {},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            ))
            cashier_name_map = {p['employeeId']: p['employeeName'] for p in profiles if p.get('employeeId')}
            g_client.close()
        except Exception:
            pass

        client.close()
        
        # UHID to Patient Mapping
        uhids = list(set(str(a.get("uhid")).strip() for a in admissions if a.get("uhid")))
        patients = Patient.objects.filter(uhid__in=uhids)
        patient_map = {}
        for p in patients:
            k = str(p.uhid).strip().upper()
            patient_map[k] = p
        
        report_data = []
        f_d = _parse_date(from_f) if from_f else None
        t_d = _parse_date(to_f) if to_f else None

        for adm in admissions:
            uhid_raw = adm.get("uhid")
            uhid_key = str(uhid_raw).strip().upper() if uhid_raw else ""
            p = patient_map.get(uhid_key)
            
            comp_code = str(adm.get("company_code") or adm.get("companyCode") or (p.company_code if p else "") or "").strip()
            comp_name = adm.get('insuranceCompanyName') or adm.get('insurance_company') or insurance_code_to_name.get(comp_code) or comp_code or "GENERAL / PRIVATE"

            if is_insurance:
                has_insurance = (
                    comp_code or 
                    adm.get('insuranceCompanyName') or 
                    adm.get('insurance_company') or 
                    (p and getattr(p, 'customer_type', '').lower() == 'insurance')
                )
                if not has_insurance:
                    continue
                
            payments = _parse_json(adm.get("advance_payments"))
            if not isinstance(payments, list):
                continue

            for pay in payments:
                if not isinstance(pay, dict):
                    continue
                if str(pay.get('status', '')).upper() in ['EDITED', 'CANCELLED']:
                    continue
                
                bill_no = pay.get('bill_no') or pay.get('receipt_no') or pay.get('advance_id') or ""

                # Date parsing
                paid_dt_val = (
                    pay.get('paid_datetime') or 
                    pay.get('created_date') or 
                    pay.get('bill_date') or 
                    pay.get('date') or 
                    adm.get('admissionDateTime') or 
                    adm.get('created_date')
                )
                paid_d = _parse_date(paid_dt_val)
                if f_d and paid_d and paid_d < f_d:
                    continue
                if t_d and paid_d and paid_d > t_d:
                    continue

                pay_outlet = (
                    pay.get('outlet_code') or 
                    adm.get('outlet_code') or 
                    ccc_map.get(bill_no, {}).get('outlet_code') or 
                    ""
                )

                ip_val = (
                    adm.get("ipNumber") or 
                    adm.get("ip_number") or 
                    adm.get("ip_no") or 
                    adm.get("inpatient_number") or 
                    pay.get("ip_number") or 
                    ""
                )
                
                # Patient Name lookup
                if p:
                    p_name = " ".join(filter(None, [getattr(p, 'salutation', ''), p.firstName, p.lastName])).strip()
                else:
                    p_name = adm.get("patient_name") or adm.get("patientname") or pay.get("patient_name") or "Patient"
                
                # Payment Mode
                p_details = pay.get('payment_details')
                if isinstance(p_details, dict):
                    p_mode = p_details.get('method') or p_details.get('payment_mode')
                else:
                    p_mode = None
                if not p_mode:
                    p_mode = pay.get('payment_mode') or pay.get('mode') or ccc_map.get(bill_no, {}).get('payment_mode') or 'Cash'
                
                # Amount extraction (handles total_advance_amount, amount, paid_amount, etc.)
                amt = _to_float(
                    pay.get('total_advance_amount') or 
                    pay.get('amount') or 
                    pay.get('paid_amount') or 
                    pay.get('advance_amount') or 
                    pay.get('ip_advance_amount') or 
                    pay.get('billing_advance_amount') or 
                    ccc_map.get(bill_no, {}).get('collected_amount')
                )
                
                # Split Cash vs Credit
                cash_amt = 0.0
                credit_amt = 0.0
                if str(p_mode).strip().lower() == "cash":
                    cash_amt = amt
                else:
                    credit_amt = amt
                
                cid = pay.get('created_by') or pay.get('cashier_id') or ccc_map.get(bill_no, {}).get('created_by') or adm.get('created_by') or ""
                user_label = cashier_name_map.get(cid) or str(cid).upper() or "STAFF"

                report_data.append({
                    "ipNumber": ip_val,
                    "ip_number": ip_val,
                    "uhid": uhid_raw or getattr(p, "uhid", ""),
                    "patient_name": p_name,
                    "patientname": p_name,
                    "age": getattr(p, "age", None) or adm.get("age"),
                    "gender": getattr(p, "gender", None) or adm.get("gender"),
                    "amount": amt,
                    "cash_amount": cash_amt,
                    "credit_amount": credit_amt,
                    "paid_date": _format_dt(paid_dt_val),
                    "date": _format_dt(paid_dt_val)[:10] if paid_dt_val else "",
                    "payment_mode": p_mode,
                    "status": pay.get('status') or "PAID",
                    "bill_no": bill_no,
                    "billnumber": bill_no,
                    "cashier_id": cid,
                    "user": user_label,
                    "outlet_code": pay_outlet,
                    "company_code": comp_code,
                    "company_name": comp_name,
                    "insurance_company": comp_name,
                    "admission_date": _format_dt(adm.get("admissionDateTime") or adm.get("created_date")),
                })
                
        report_data.sort(key=lambda x: x["paid_date"] or "", reverse=True)
        return Response({"success": True, "data": report_data})
    except Exception as e:
        import traceback
        print("Advance Registration Error:", str(e))
        print(traceback.format_exc())
        return Response({"success": False, "message": str(e)}, status=500)

@api_view(["POST", "GET"])
# @permission_classes([HasRoleAndDataPermission])
def bill_cancel_report(request):
    try:
        # Connect MongoDB
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]
        
        # 1. Fetch cancelled discharge billing where is_cancelled = True or status = "Cancelled"
        discharge_query = {
            "$or": [
                {"is_cancelled": True},
                {"status": "Cancelled"}
            ]
        }
        discharge_bills = list(db["hospital_dischargebilling"].find(discharge_query))
        
        # 2. Fetch admissions containing cancelled advance payments or cancelled admission itself
        admission_query = {
            "$or": [
                {"is_cancelled": True},
                {"status": "Cancelled"},
                {"advance_payments.status": "Cancelled"},
                {"advance_payments.is_cancelled": True}
            ]
        }
        admissions = list(db["hospital_admission"].find(admission_query))
        
        # 3. Gather all unique UHIDs
        uhids = []
        for b in discharge_bills:
            uhid = b.get("uhid")
            if uhid: uhids.append(uhid)
        for a in admissions:
            uhid = a.get("uhid")
            if uhid: uhids.append(uhid)
            
        uhids = list(set(uhids))
        
        # 4. Resolve patients info in bulk
        patient_map = {}
        if uhids:
            patients = list(db["hospital_patient"].find({"uhid": {"$in": uhids}}))
            for p in patients:
                patient_map[p["uhid"]] = p
                
        # 5. Build results
        results = []
        
        # A. Discharge Billing
        for b in discharge_bills:
            uhid = b.get("uhid")
            p = patient_map.get(uhid, {})
            
            bill_date = b.get("bill_date") or b.get("created_date")
            cancelled_date = b.get("lastmodified_date") or bill_date
            
            results.append({
                "bill_no": b.get("bill_no") or b.get("estimate_number") or f"DCH-{b.get('discharge_id')}",
                "uhid": uhid,
                "patient_name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or "Unknown",
                "age": p.get("age"),
                "gender": p.get("gender"),
                "bill_type": "Discharge Bill",
                "bill_date": _format_dt(bill_date),
                "cancelled_date": _format_dt(cancelled_date),
                "net_amount": _to_float(b.get("net_amount") or b.get("total_amount")),
                "created_by": b.get("created_by") or "",
                "cancelled_by": b.get("lastmodified_by") or b.get("created_by") or "",
                "remarks": b.get("remarks") or b.get("disc_reason") or "",
                "status": "Cancelled"
            })
            
        # B. IP Advance / Admission from Admission
        for adm in admissions:
            uhid = adm.get("uhid")
            p = patient_map.get(uhid, {})
            
            # 1. Check if the admission document itself is cancelled
            if adm.get("is_cancelled") == True:
                bill_date = adm.get("admissionDateTime") or adm.get("created_date")
                cancelled_date = adm.get("lastmodified_date") or bill_date
                
                results.append({
                    "bill_no": adm.get("ipNumber") or "N/A",
                    "uhid": uhid,
                    "patient_name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or "Unknown",
                    "age": p.get("age"),
                    "gender": p.get("gender"),
                    "bill_type": "IP Admission",
                    "bill_date": _format_dt(bill_date),
                    "cancelled_date": _format_dt(cancelled_date),
                    "net_amount": 0.0,
                    "created_by": adm.get("created_by") or "",
                    "cancelled_by": adm.get("lastmodified_by") or adm.get("created_by") or "",
                    "remarks": adm.get("mlc_remarks") or adm.get("remarks") or "Admission Cancelled",
                    "status": "Cancelled"
                })
            
            # 2. Check individual advance payments inside the admission document
            adv_payments = adm.get("advance_payments") or []
            if isinstance(adv_payments, str):
                try: adv_payments = _json.loads(adv_payments)
                except: adv_payments = []
                
            for pay in adv_payments:
                if not isinstance(pay, dict):
                    continue
                    
                is_cancelled_pay = (pay.get("status") == "Cancelled" or pay.get("is_cancelled") == True)
                if is_cancelled_pay:
                    bill_date = pay.get("bill_date") or pay.get("created_date") or pay.get("date")
                    cancelled_date = pay.get("cancelled_date") or pay.get("lastmodified_date") or bill_date
                    
                    results.append({
                        "bill_no": pay.get("bill_no") or pay.get("advance_id") or "N/A",
                        "uhid": uhid,
                        "patient_name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or "Unknown",
                        "age": p.get("age"),
                        "gender": p.get("gender"),
                        "bill_type": "IP Advance",
                        "bill_date": _format_dt(bill_date),
                        "cancelled_date": _format_dt(cancelled_date),
                        "net_amount": _to_float(pay.get("advance_amount") or pay.get("amount")),
                        "created_by": pay.get("created_by") or adm.get("created_by") or "",
                        "cancelled_by": pay.get("cancelled_by") or pay.get("lastmodified_by") or "",
                        "remarks": pay.get("remarks") or pay.get("disc_reason") or "",
                        "status": "Cancelled"
                    })
                    
        client.close()
        
        # 6. Apply Date Filtering
        params = request.data if request.method == "POST" else request.GET
        from_date = params.get("from_date")
        to_date = params.get("to_date")
        
        filtered_results = []
        if from_date or to_date:
            f_dt = _parse_date(from_date) if from_date else None
            t_dt = _parse_date(to_date) if to_date else None
            
            for r in results:
                c_date_str = r.get("cancelled_date") or r.get("bill_date")
                c_date = _parse_date(c_date_str)
                if c_date:
                    if f_dt and c_date < f_dt:
                        continue
                    if t_dt and c_date > t_dt:
                        continue
                filtered_results.append(r)
        else:
            filtered_results = results
            
        # Sort by cancelled_date desc
        filtered_results.sort(key=lambda x: x["cancelled_date"] or x["bill_date"] or "", reverse=True)
        
        return Response({"success": True, "data": filtered_results})
        
    except Exception as e:
        import traceback
        print("Bill Cancel Report Error:", str(e))
        print(traceback.format_exc())
        return Response({"success": False, "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# Credit Card Report
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def credit_card_report(request):
    """
    Lists every Card-mode collection grouped by Date and Category/Department
    (e.g., PHARMACY OP BILL (SH), PHARMACY IP BILL (SH), ADVANCE, DISCHARGE,
    CT SCAN (SH), ECG (SH), LAB BILL (SH), PET_CT(SH), PROCEDURE BILL (SH),
    REGISTRATION(SH), SCANNING (SH), X - RAY (SH), XEROX (SH), etc.).
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        from_date_str = data.get("from_date")
        to_date_str = data.get("to_date")
        outlet_code = data.get("outlet_code") or data.get("outlet")
        hospital_code, branch_code = _auth_scope(request)

        if not from_date_str:
            from_date_str = datetime.now().strftime("%Y-%m-%d")
        if not to_date_str:
            to_date_str = datetime.now().strftime("%Y-%m-%d")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        def _is_card(val):
            if not val: return False
            if isinstance(val, dict):
                val = val.get("method") or val.get("payment_mode") or ""
            s = str(val).strip().lower()
            return any(k in s for k in ["card", "credit", "debit", "pos", "swipe", "paytm", "pinelabs"])

        def _get_card_details(pd, mode_str=""):
            if isinstance(pd, str):
                try: pd = _json.loads(pd)
                except: pd = {}
            if not isinstance(pd, dict): pd = {}
            mode_upper = str(mode_str or "").upper()
            c_type = pd.get("card_type") or pd.get("cardType") or pd.get("card_name") or ""
            if not c_type:
                if "RUPAY" in mode_upper: c_type = "RUPAY CARD"
                elif "VISA" in mode_upper: c_type = "VISA CARD"
                elif "MASTER" in mode_upper: c_type = "MASTER CARD"
                elif "AMEX" in mode_upper or "AMERICAN" in mode_upper: c_type = "AMEX CARD"
                elif "DEBIT" in mode_upper: c_type = "DEBIT CARD"
                elif "CREDIT" in mode_upper: c_type = "CREDIT CARD"
                else: c_type = "CARD"
            else:
                c_type = str(c_type).upper()
                if not ("CARD" in c_type): c_type = f"{c_type} CARD"

            c_num = pd.get("card_number") or pd.get("cardNumber") or pd.get("card_no") or pd.get("pos_machine") or pd.get("machine") or pd.get("pos") or pd.get("transaction_id") or ""
            if not c_num:
                if "PAYTM" in mode_upper: c_num = "PAYTM"
                elif "PINE" in mode_upper: c_num = "PINELABS"
                elif "HDFC" in mode_upper: c_num = "HDFC POS"
                elif "SBI" in mode_upper: c_num = "SBI POS"
                else: c_num = "POS"
            else:
                c_num = str(c_num).upper()
            return c_type, c_num

        mongo_query = {}
        if hospital_code: mongo_query["hospital_code"] = hospital_code
        if branch_code: mongo_query["branch_code"] = branch_code
        if outlet_code and str(outlet_code).strip().lower() != "all":
            mongo_query["outlet_code"] = outlet_code
        mongo_query["created_date"] = {"$gte": from_date, "$lte": to_date}

        ccc_docs = list(db["hospital_cashcountercollection"].find(mongo_query))
        enriched_data = fetch_detailed_billing_data(db, ccc_docs)

        raw_rows = []
        seen_bills = set()

        for r in enriched_data:
            if r.get("type") == "Sales Return":
                continue

            b_no = r.get("bill_no")
            if b_no and b_no in seen_bills: continue
            if b_no: seen_bills.add(b_no)

            p_mode = str(r.get("payment_mode") or "").strip()
            pd = r.get("payment_details") or {}
            
            card_amt = 0.0
            if _is_card(p_mode):
                card_amt = _to_float(r.get("display_amount") or r.get("net_amount"))
            elif "multiple" in p_mode.lower():
                breakdown = pd.get("breakdown") or []
                card_amt = sum(
                    _to_float(b.get("Paid_amount") or b.get("amount") or b.get("paid_amount"))
                    for b in breakdown if isinstance(b, dict) and _is_card(b.get("method") or b.get("payment_mode"))
                )

            if card_amt <= 0:
                continue

            cat_title = r.get("type_name") or r.get("type") or "OTHER"
            c_type, c_num = _get_card_details(pd, p_mode)
            b_date_str = str(r.get("bill_date") or from_date_str)[:10]

            raw_rows.append({
                "date_raw": r.get("bill_date") or from_date_str,
                "date": b_date_str,
                "category": cat_title,
                "bill_no": b_no or "N/A",
                "uhid": str(r.get("uhid") or ""),
                "mr_no": str(r.get("uhid") or ""),
                "patient_name": "",
                "cashier_id": r.get("cashier_id") or "",
                "card_type": c_type,
                "card_number": c_num,
                "amount": card_amt,
                "user": str(r.get("cashier_id") or "STAFF").upper()
            })

        # Fetch Patient Names
        uhids = list(set([r["uhid"] for r in raw_rows if r.get("uhid")]))
        patients = list(db["hospital_patient"].find({"uhid": {"$in": uhids}}, {"uhid": 1, "firstName": 1, "lastName": 1}))
        patient_map = {p["uhid"]: f"{p['firstName']} {p['lastName']}".strip() for p in patients}

        # Fetch Cashier Names (Global DB)
        cashier_ids = list(set([r["cashier_id"] for r in raw_rows if r.get("cashier_id")]))
        cashier_name_map = {}
        try:
            g_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            g_db = g_client['Global']
            profiles = list(g_db['backend_diagnostics_profile'].find(
                {"employeeId": {"$in": cashier_ids}},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            ))
            cashier_name_map = {p['employeeId']: p['employeeName'] for p in profiles}
            g_client.close()
        except: pass

        for r in raw_rows:
            r["patient_name"] = patient_map.get(r["uhid"]) or (f"Patient #{r['uhid']}" if r["uhid"] else "General / Cash Patient")
            if r.get("cashier_id") and r["cashier_id"] in cashier_name_map:
                r["user"] = cashier_name_map[r["cashier_id"]].upper()

            dt_obj = _parse_date(r["date_raw"])
            if dt_obj:
                r["date"] = dt_obj.strftime("%Y-%m-%d")
                r["date_display"] = dt_obj.strftime("%d/%m/%Y")
            else:
                r["date"] = str(r["date_raw"])[:10]
                r["date_display"] = str(r["date_raw"])[:10]
            if "date_raw" in r: del r["date_raw"]
            if "cashier_id" in r: del r["cashier_id"]

        client.close()

        # Sort all rows by date asc, category asc, bill_no asc
        raw_rows.sort(key=lambda x: (x["date"], x["category"], x["bill_no"]))

        # Build Grouped Data structure matching hospital PDF report
        # Date -> Sections (Categories) -> Transactions
        date_groups = {}
        for r in raw_rows:
            d_key = r["date"]
            d_disp = r["date_display"]
            cat = r["category"]

            if d_key not in date_groups:
                date_groups[d_key] = {
                    "date": d_key,
                    "date_display": d_disp,
                    "sections": {},
                    "date_total": 0.0,
                    "count": 0
                }

            dg = date_groups[d_key]
            if cat not in dg["sections"]:
                dg["sections"][cat] = {
                    "category": cat,
                    "items": [],
                    "total": 0.0,
                    "count": 0
                }

            sec = dg["sections"][cat]
            sec["items"].append(r)
            sec["total"] += r["amount"]
            sec["count"] += 1
            dg["date_total"] += r["amount"]
            dg["count"] += 1

        grouped_result = []
        flat_rows_with_slno = []
        global_slno = 1

        for d_key in sorted(date_groups.keys()):
            dg = date_groups[d_key]
            sec_list = []
            for cat_name in sorted(dg["sections"].keys()):
                sec_obj = dg["sections"][cat_name]
                for item in sec_obj["items"]:
                    item["slno"] = global_slno
                    global_slno += 1
                    flat_rows_with_slno.append(item)
                sec_list.append({
                    "category": sec_obj["category"],
                    "items": sec_obj["items"],
                    "total": sec_obj["total"],
                    "count": sec_obj["count"]
                })
            grouped_result.append({
                "date": dg["date"],
                "date_display": dg["date_display"],
                "sections": sec_list,
                "date_total": dg["date_total"],
                "count": dg["count"]
            })

        grand_total = sum(r["amount"] for r in flat_rows_with_slno)
        by_category_summary = {}
        for r in flat_rows_with_slno:
            by_category_summary[r["category"]] = by_category_summary.get(r["category"], 0.0) + r["amount"]

        summary = {
            "total_transactions": len(flat_rows_with_slno),
            "total_amount": grand_total,
            "by_type": by_category_summary,
            "by_category": by_category_summary
        }

        return Response({
            "success": True,
            "data": flat_rows_with_slno,
            "grouped_data": grouped_result,
            "summary": summary,
            "grand_total": grand_total
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# Cash Bills Report
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def cash_bills_report(request):
    """
    Lists every Cash-mode collection grouped by Date and Category/Department
    (e.g., PHARMACY OP BILL (SH), PHARMACY IP BILL (SH), ADVANCE, DISCHARGE,
    CT SCAN (SH), ECG (SH), LAB BILL (SH), PET_CT(SH), PROCEDURE BILL (SH),
    REGISTRATION(SH), SCANNING (SH), X - RAY (SH), XEROX (SH), etc.).
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        from_date_str = data.get("from_date")
        to_date_str = data.get("to_date")
        outlet_code = data.get("outlet_code") or data.get("outlet")
        hospital_code, branch_code = _auth_scope(request)

        if not from_date_str:
            from_date_str = datetime.now().strftime("%Y-%m-%d")
        if not to_date_str:
            to_date_str = datetime.now().strftime("%Y-%m-%d")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        mongo_query = {}
        if hospital_code: mongo_query["hospital_code"] = hospital_code
        if branch_code: mongo_query["branch_code"] = branch_code
        if outlet_code and str(outlet_code).strip().lower() != "all":
            mongo_query["outlet_code"] = outlet_code
        mongo_query["created_date"] = {"$gte": from_date, "$lte": to_date}

        ccc_docs = list(db["hospital_cashcountercollection"].find(mongo_query))
        enriched_data = fetch_detailed_billing_data(db, ccc_docs)

        raw_rows = []
        seen_bills = set()

        for r in enriched_data:
            if r.get("type") == "Sales Return":
                continue

            b_no = r.get("bill_no")
            if b_no and b_no in seen_bills: continue
            if b_no: seen_bills.add(b_no)

            p_mode = str(r.get("payment_mode") or "Cash").strip()
            pd = r.get("payment_details") or {}
            
            cash_amt = 0.0
            is_cash = False

            if p_mode.lower() == "cash" or not p_mode:
                is_cash = True
                cash_amt = _to_float(r.get("display_amount") or r.get("net_amount"))
            elif "multiple" in p_mode.lower():
                breakdown = pd.get("breakdown") or []
                cash_total = sum(
                    _to_float(b.get("Paid_amount") or b.get("amount") or b.get("paid_amount"))
                    for b in breakdown if isinstance(b, dict) and "cash" in str(b.get("method") or b.get("payment_mode") or "").lower()
                )
                if cash_total > 0:
                    is_cash = True
                    cash_amt = cash_total
                elif not breakdown:
                    is_cash = True
                    cash_amt = _to_float(r.get("display_amount") or r.get("net_amount"))
            elif "cash" in p_mode.lower():
                is_cash = True
                cash_amt = _to_float(r.get("display_amount") or r.get("net_amount"))

            if not is_cash or cash_amt <= 0:
                continue

            cat_title = r.get("type_name") or r.get("type") or "OTHER"
            b_date_str = str(r.get("bill_date") or from_date_str)[:10]

            raw_rows.append({
                "date_raw": r.get("bill_date") or from_date_str,
                "date": b_date_str,
                "category": cat_title,
                "bill_no": b_no or "N/A",
                "uhid": str(r.get("uhid") or ""),
                "mr_no": str(r.get("uhid") or ""),
                "patient_name": "",
                "cashier_id": r.get("cashier_id") or "",
                "payment_mode": "CASH",
                "amount": cash_amt,
                "user": str(r.get("cashier_id") or "STAFF").upper()
            })

        # Fetch Patient Names
        uhids = list(set([r["uhid"] for r in raw_rows if r.get("uhid")]))
        patients = list(db["hospital_patient"].find({"uhid": {"$in": uhids}}, {"uhid": 1, "firstName": 1, "lastName": 1}))
        patient_map = {p["uhid"]: f"{p['firstName']} {p['lastName']}".strip() for p in patients}

        # Fetch Cashier Names (Global DB)
        cashier_ids = list(set([r["cashier_id"] for r in raw_rows if r.get("cashier_id")]))
        cashier_name_map = {}
        try:
            g_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            g_db = g_client['Global']
            profiles = list(g_db['backend_diagnostics_profile'].find(
                {"employeeId": {"$in": cashier_ids}},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            ))
            cashier_name_map = {p['employeeId']: p['employeeName'] for p in profiles}
            g_client.close()
        except: pass

        for r in raw_rows:
            r["patient_name"] = patient_map.get(r["uhid"]) or (f"Patient #{r['uhid']}" if r["uhid"] else "General / Cash Patient")
            if r.get("cashier_id") and r["cashier_id"] in cashier_name_map:
                r["user"] = cashier_name_map[r["cashier_id"]].upper()

            dt_obj = _parse_date(r["date_raw"])
            if dt_obj:
                r["date"] = dt_obj.strftime("%Y-%m-%d")
                r["date_display"] = dt_obj.strftime("%d/%m/%Y")
            else:
                r["date"] = str(r["date_raw"])[:10]
                r["date_display"] = str(r["date_raw"])[:10]
            if "date_raw" in r: del r["date_raw"]
            if "cashier_id" in r: del r["cashier_id"]

        client.close()

        # Sort all rows by date asc, category asc, bill_no asc
        raw_rows.sort(key=lambda x: (x["date"], x["category"], x["bill_no"]))

        # Build Grouped Data structure matching hospital PDF report
        # Date -> Sections (Categories) -> Transactions
        date_groups = {}
        for r in raw_rows:
            d_key = r["date"]
            d_disp = r["date_display"]
            cat = r["category"]

            if d_key not in date_groups:
                date_groups[d_key] = {
                    "date": d_key,
                    "date_display": d_disp,
                    "sections": {},
                    "date_total": 0.0,
                    "count": 0
                }

            dg = date_groups[d_key]
            if cat not in dg["sections"]:
                dg["sections"][cat] = {
                    "category": cat,
                    "items": [],
                    "total": 0.0,
                    "count": 0
                }

            sec = dg["sections"][cat]
            sec["items"].append(r)
            sec["total"] += r["amount"]
            sec["count"] += 1
            dg["date_total"] += r["amount"]
            dg["count"] += 1

        grouped_result = []
        flat_rows_with_slno = []
        global_slno = 1

        for d_key in sorted(date_groups.keys()):
            dg = date_groups[d_key]
            sec_list = []
            for cat_name in sorted(dg["sections"].keys()):
                sec_obj = dg["sections"][cat_name]
                for item in sec_obj["items"]:
                    item["slno"] = global_slno
                    global_slno += 1
                    flat_rows_with_slno.append(item)
                sec_list.append({
                    "category": sec_obj["category"],
                    "items": sec_obj["items"],
                    "total": sec_obj["total"],
                    "count": sec_obj["count"]
                })
            grouped_result.append({
                "date": dg["date"],
                "date_display": dg["date_display"],
                "sections": sec_list,
                "date_total": dg["date_total"],
                "count": dg["count"]
            })

        grand_total = sum(r["amount"] for r in flat_rows_with_slno)
        by_category_summary = {}
        for r in flat_rows_with_slno:
            by_category_summary[r["category"]] = by_category_summary.get(r["category"], 0.0) + r["amount"]

        summary = {
            "total_transactions": len(flat_rows_with_slno),
            "total_amount": grand_total,
            "by_type": by_category_summary,
            "by_category": by_category_summary
        }

        return Response({
            "success": True,
            "data": flat_rows_with_slno,
            "grouped_data": grouped_result,
            "summary": summary,
            "grand_total": grand_total
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# Date Wise Collection Summary Report
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def date_wise_collection_summary_report(request):
    """
    Returns Date Wise Collection Summary Report grouped by Date and Bill Type/Category,
    matching Shanmuga Hospital Limited collection summary format.
    """
    try:
        from_d_str = request.GET.get("from_date")
        to_d_str = request.GET.get("to_date")
        hospital_code, branch_code = _auth_scope(request)

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client[os.getenv("HMS_DB_NAME", "HMS")]

        # Date query
        f_d = _parse_date(from_d_str) if from_d_str else date.today()
        t_d = _parse_date(to_d_str) if to_d_str else date.today()

        f_dt = datetime.combine(f_d, datetime.min.time())
        t_dt = datetime.combine(t_d, datetime.max.time())

        date_q = {"created_date": {"$gte": f_dt, "$lte": t_dt}}
        if hospital_code:
            date_q["hospital_code"] = hospital_code
        if branch_code:
            date_q["branch_code"] = branch_code

        # Fetch cash counter collections
        ccc_docs = list(db["hospital_cashcountercollection"].find(date_q))

        # Fetch all bill types for mapping
        billtype_map = {}
        billtype_id_map = {}
        try:
            bt_list = list(db["hospital_billtype"].find({}, {"billTypeNo": 1, "bill_name": 1, "bill_type": 1}))
            for bt in bt_list:
                bt_no = bt.get("billTypeNo")
                bt_name = bt.get("bill_name")
                bt_id = bt.get("bill_type")
                if bt_no and bt_name:
                    billtype_map[str(bt_no).strip()] = str(bt_name).strip()
                if bt_id is not None and bt_name:
                    billtype_id_map[str(bt_id).strip()] = str(bt_name).strip()
        except Exception as e:
            print("Error fetching bill types:", e)

        # Pre-group bill_numbers by billing_category for bulk queries
        by_category = {}
        for r in ccc_docs:
            cat = r.get("billing_category")
            if not cat:
                continue
            by_category.setdefault(cat, []).append(r)

        def fetch_docs(collection_name, field_name, bill_numbers):
            if not bill_numbers:
                return {}
            docs = list(db[collection_name].find({field_name: {"$in": bill_numbers}}))
            return {str(d[field_name]): d for d in docs if field_name in d}

        def get_bill_nums(records):
            nums = []
            for r in records:
                b_no = r.get("bill_no") or r.get("bill_number")
                if b_no:
                    nums.append(str(b_no))
            return list(set(nums))

        # 1. Pharmacy
        pharmacy_bills = by_category.get("OPPharmacyBills", []) + by_category.get("Pharmacy", []) + by_category.get("PharmacyBills", [])
        pharmacy_nums = get_bill_nums(pharmacy_bills)
        pharmacy_map = fetch_docs("hospital_pharmacybilling", "bill_no", pharmacy_nums)

        # 2. Investigation
        invest_bills = by_category.get("Investigation", []) + by_category.get("InvestigationBills", [])
        invest_nums = get_bill_nums(invest_bills)
        invest_map = fetch_docs("hospital_investbilling", "investBillNo", invest_nums)

        # 3. Billing (Registration/Consultation)
        billing_bills = by_category.get("Billing", []) + by_category.get("Registration", []) + by_category.get("RegistrationBills", [])
        billing_nums = get_bill_nums(billing_bills)
        billing_map = fetch_docs("hospital_billing", "bill_number", billing_nums)

        # 4. Discharge
        discharge_bills = by_category.get("Discharge", []) + by_category.get("DischargeBills", [])
        discharge_nums = get_bill_nums(discharge_bills)
        discharge_map = fetch_docs("hospital_dischargebilling", "bill_no", discharge_nums)

        # 5. IPAdvance
        advance_bills = by_category.get("IPAdvance", []) + by_category.get("IPAdvanceBills", []) + by_category.get("IPAdvance Payment", []) + by_category.get("Advance", [])
        advance_nums = get_bill_nums(advance_bills)
        advance_map = {}
        if advance_nums:
            adms = list(db["hospital_admission"].find({"advance_payments.bill_no": {"$in": advance_nums}}))
            for adm in adms:
                pays = adm.get("advance_payments", [])
                for p in pays:
                    if isinstance(p, dict):
                        b_no = str(p.get("bill_no"))
                        if b_no in advance_nums:
                            advance_map[b_no] = {
                                "admission": adm,
                                "payment": p
                            }

        # 6. Sales Return
        sales_return_bills = by_category.get("Sales Return", []) + by_category.get("sales_return", [])
        sales_return_nums = get_bill_nums(sales_return_bills)
        sales_return_map = fetch_docs("hospital_salesreturn", "return_bill_no", sales_return_nums)

        # 7. Receipt / Payment
        rp_bills = by_category.get("Receipt", []) + by_category.get("Payment", [])
        rp_nums = get_bill_nums(rp_bills)
        rp_map = fetch_docs("hospital_receiptandpayment", "voucher_no", rp_nums)

        # Group by (Date, Bill Category)
        summary_map = {}

        for doc in ccc_docs:
            d_val = doc.get("created_date")
            d_str = d_val.strftime("%Y-%m-%d") if isinstance(d_val, datetime) else str(d_val)[:10]
            
            cat = doc.get("billing_category") or ""
            bt = doc.get("bill_type")
            bill_no = str(doc.get("bill_no") or doc.get("bill_number") or "")

            # Resolve bill type name
            bill_name = None
            if bt is not None and str(bt).strip() in billtype_id_map:
                bill_name = billtype_id_map[str(bt).strip()]
            elif doc.get("billTypeNo") and str(doc.get("billTypeNo")).strip() in billtype_map:
                bill_name = billtype_map[str(doc.get("billTypeNo")).strip()]

            gross = 0.0
            disc = 0.0
            bill_adv = 0.0
            ip_return = 0.0
            sales_ret = 0.0
            ip_credit = 0.0
            p_debit = 0.0
            debit_col = 0.0
            adv_refd = 0.0
            net = _to_float(doc.get("collected_amount") or doc.get("net_amount"))
            cash = 0.0
            bank = 0.0

            p_details = {}
            p_mode = ""

            if cat in ["OPPharmacyBills", "Pharmacy", "PharmacyBills"] and bill_no in pharmacy_map:
                d = pharmacy_map[bill_no]
                if not bill_name:
                    is_ip = bool(d.get("inpatient_number") or d.get("ip_no") or d.get("admission_id"))
                    bill_name = "PHARMACY IP BILL" if is_ip else "PHARMACY OP BILL"
                gross = _to_float(d.get("total_amount") or d.get("gross_amount")) or net
                disc = _to_float(d.get("overall_discount_amount") or d.get("discount"))
                net = _to_float(d.get("net_amount")) or net
                p_details = d.get("payment_details") or {}
                p_mode = d.get("payment_mode") or d.get("payment_method") or ""
            elif cat in ["Investigation", "InvestigationBills"] and bill_no in invest_map:
                d = invest_map[bill_no]
                if not bill_name:
                    bt_no = str(d.get("billTypeNo") or "").strip()
                    bt_id = str(d.get("bill_type") or "").strip()
                    bill_name = billtype_map.get(bt_no) or billtype_id_map.get(bt_id) or "INVESTIGATION"
                gross = _to_float(d.get("total") or d.get("gross_amount")) or net
                disc = _to_float(d.get("discount"))
                net = _to_float(d.get("finalPrice") or d.get("total")) or net
                p_details = d.get("payment_details") or {}
                p_mode = d.get("paymentMethod") or d.get("payment_method") or ""
            elif cat in ["Billing", "Registration", "RegistrationBills"] and bill_no in billing_map:
                d = billing_map[bill_no]
                if not bill_name:
                    bt_id = str(d.get("bill_type") or "").strip()
                    bill_name = billtype_id_map.get(bt_id) or "REGISTRATION"
                gross = _to_float(d.get("total_fees") or (d.get("registration_fee", 0) + d.get("consulting_fee", 0))) or net
                disc = _to_float(d.get("discount"))
                net = _to_float(d.get("total_fees")) or net
                p_details = d.get("payment_details") or {}
                p_mode = d.get("payment_method") or d.get("payment_mode") or ""
            elif cat in ["Discharge", "DischargeBills"] and bill_no in discharge_map:
                d = discharge_map[bill_no]
                if not bill_name:
                    bill_name = "DISCHARGE"
                gross = _to_float(d.get("total_amount") or d.get("gross_amount")) or net
                disc = _to_float(d.get("discount_amount") or d.get("discount"))
                bill_adv = _to_float(d.get("advance_amount") or d.get("advance_adjusted"))
                sales_ret = _to_float(d.get("sales_return"))
                net = _to_float(d.get("net_amount") or d.get("paid_amount")) or net
                p_details = d.get("payment_details") or {}
                p_mode = d.get("payment_mode") or d.get("payment_method") or ""
            elif cat in ["IPAdvance Payment", "IPAdvance", "Advance"] and bill_no in advance_map:
                d = advance_map[bill_no]
                pay = d["payment"]
                if not bill_name:
                    bill_name = "ADVANCE"
                gross = _to_float(pay.get("advance_amount") or pay.get("amount")) or net
                net = gross
                p_details = pay.get("payment_details") or {}
                p_mode = pay.get("payment_mode") or pay.get("payment_method") or ""
            elif cat in ["Sales Return", "sales_return"] and bill_no in sales_return_map:
                d = sales_return_map[bill_no]
                if not bill_name:
                    bill_name = "SALES RETURNS"
                sales_ret = _to_float(d.get("return_amount")) or abs(net)
                net = -abs(sales_ret)
                p_mode = d.get("PaymentType") or "Cash"
            elif cat in ["Receipt", "Payment"] and bill_no in rp_map:
                d = rp_map[bill_no]
                amt = _to_float(d.get("amount"))
                if not bill_name:
                    bill_name = "MISCELLANEOUS INCOME" if cat == "Receipt" else "MISCELLANEOUS EXPENSE"
                gross = amt
                net = -abs(amt) if cat == "Payment" else amt
                p_mode = d.get("payment_mode") or "Cash"
            else:
                if not bill_name:
                    if cat in ["OPPharmacyBills", "Pharmacy", "PharmacyBills"]: bill_name = "PHARMACY OP BILL"
                    elif cat in ["Billing", "Registration", "RegistrationBills"]: bill_name = "REGISTRATION"
                    elif cat in ["IPAdvance Payment", "IPAdvance", "Advance"]: bill_name = "ADVANCE"
                    elif cat in ["Discharge", "DischargeBills"]: bill_name = "DISCHARGE"
                    elif cat in ["Investigation", "InvestigationBills"]: bill_name = "INVESTIGATION"
                    elif cat in ["remitted"]: bill_name = "REMITTED TO BANK"
                    elif cat in ["submit"]: bill_name = "SUBMITTED TO ACCOUNT"
                    elif doc.get("department"): bill_name = str(doc.get("department"))
                    else: bill_name = "GENERAL"
                gross = net

            # Split or single payment calculation for Cash vs Bank
            breakdown = p_details.get("breakdown") if isinstance(p_details, dict) else None
            if breakdown and isinstance(breakdown, list):
                cash_part = sum(
                    _to_float(b.get("Paid_amount") or b.get("amount") or b.get("paid_amount"))
                    for b in breakdown if isinstance(b, dict) and "cash" in str(b.get("method") or b.get("payment_mode") or "").lower()
                )
                bank_part = sum(
                    _to_float(b.get("Paid_amount") or b.get("amount") or b.get("paid_amount"))
                    for b in breakdown if isinstance(b, dict) and "cash" not in str(b.get("method") or b.get("payment_mode") or "").lower()
                )
                if cash_part > 0 or bank_part > 0:
                    cash = cash_part
                    bank = bank_part
                else:
                    cash = net
            else:
                method = str((p_details.get("method") if isinstance(p_details, dict) else "") or p_mode or doc.get("payment_mode") or doc.get("payment_method") or "cash").lower().strip()
                if "cash" in method or method == "":
                    cash = net
                else:
                    bank = net

            key = (d_str, bill_name)
            if key not in summary_map:
                summary_map[key] = {
                    "date": d_str,
                    "bill_name": bill_name,
                    "bill_nos": [],
                    "gross_amount": 0.0,
                    "discount": 0.0,
                    "bill_adv": 0.0,
                    "ip_return": 0.0,
                    "sales_ret": 0.0,
                    "ip_credit": 0.0,
                    "p_debit": 0.0,
                    "debit_col": 0.0,
                    "adv_refd": 0.0,
                    "net_amount": 0.0,
                    "cash": 0.0,
                    "bank": 0.0
                }

            row = summary_map[key]
            if bill_no:
                row["bill_nos"].append(bill_no)

            row["gross_amount"] += gross
            row["discount"] += disc
            row["bill_adv"] += bill_adv
            row["ip_return"] += ip_return
            row["sales_ret"] += sales_ret
            row["ip_credit"] += ip_credit
            row["p_debit"] += p_debit
            row["debit_col"] += debit_col
            row["adv_refd"] += adv_refd
            row["net_amount"] += net
            row["cash"] += cash
            row["bank"] += bank

        # Format Bill Ranges and round decimals
        results = []
        for (d_str, bill_name), row in sorted(summary_map.items()):
            nos = row.pop("bill_nos")
            if nos:
                nos.sort()
                row["bill_range"] = f"{nos[0]}To{nos[-1]}"
            else:
                row["bill_range"] = ""

            for k in ["gross_amount", "discount", "bill_adv", "ip_return", "sales_ret", "ip_credit", "p_debit", "debit_col", "adv_refd", "net_amount", "cash", "bank"]:
                row[k] = round(row[k], 2)

            results.append(row)

        client.close()
        return Response({"success": True, "data": results})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# Miscellaneous Payment Report (Receipt & Payment vouchers)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def miscellaneous_payment_report(request):
    """
    Lists Receipt & Payment vouchers (ad hoc collections/disbursements posted
    against an account head, e.g. 'Miscellaneous Income') for a date range.

    Query params:
    - account_head: exact account head to filter by (omit/'all' = every head)
    - receipt_type: 'Receipt' | 'Payment' (omit/'all' = both)
    """
    try:
        from_f = request.GET.get("from_date")
        to_f   = request.GET.get("to_date")
        account_head_f = request.GET.get("account_head")
        receipt_type_f = request.GET.get("receipt_type")

        qs = ReceiptAndPayment.objects.all()
        if from_f:
            f_date = _parse_date(from_f)
            if f_date: qs = qs.filter(voucher_date__gte=f_date)
        if to_f:
            t_date = _parse_date(to_f)
            if t_date: qs = qs.filter(voucher_date__lte=t_date)
        if account_head_f and account_head_f.lower() != "all":
            qs = qs.filter(account_head=account_head_f)
        if receipt_type_f and receipt_type_f.lower() != "all":
            qs = qs.filter(receipt_type=receipt_type_f)

        records = list(qs.order_by("-voucher_date"))

        cashier_ids = {r.CashierID for r in records if r.CashierID}
        cashier_map = {}
        if cashier_ids:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            try:
                profiles = client["Global"]["backend_diagnostics_profile"].find(
                    {"employeeId": {"$in": list(cashier_ids)}}, {"employeeId": 1, "employeeName": 1}
                )
                cashier_map = {str(p["employeeId"]): p.get("employeeName", "") for p in profiles}
            except Exception:
                pass
            client.close()

        data = []
        for r in records:
            desc_str = _format_description(r.description)
            data.append({
                "voucher_no": r.voucher_no,
                "voucher_date": r.voucher_date.isoformat() if r.voucher_date else None,
                "receipt_type": r.receipt_type,
                "account_head": r.account_head,
                "amount": _to_float(r.amount),
                "shiftno": r.shiftno,
                "cashier_name": cashier_map.get(str(r.CashierID), r.CashierID or ""),
                "description": desc_str,
            })

        total_receipts = sum(d["amount"] for d in data if d["receipt_type"] == "Receipt")
        total_payments = sum(d["amount"] for d in data if d["receipt_type"] == "Payment")
        summary = {
            "count": len(data),
            "total_receipts": total_receipts,
            "total_payments": total_payments,
            "net": total_receipts - total_payments,
        }

        return Response({"success": True, "data": data, "summary": summary})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# A/c Papers — Daily Cash Report (Cash Book)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def daily_cash_report(request):
    """
    Day-wise Cash Book: Cash-mode collections across Registration (OP),
    Pharmacy, and Discharge billing (cash IN), combined with Receipt &
    Payment vouchers — Receipts add to cash IN, Payments are cash OUT.

    Note: this does not include any external POS/retail system — only
    sources tracked inside this HMS application.
    """
    try:
        from_f = request.GET.get("from_date")
        to_f   = request.GET.get("to_date")
        hospital_code, branch_code = _auth_scope(request)

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        q = {"billing_category": {"$in": [
            "Billing", "Registration", "RegistrationBills",
            "OPPharmacyBills", "Pharmacy", "PharmacyBills",
            "Discharge", "DischargeBills",
        ]}}
        if hospital_code: q["hospital_code"] = hospital_code
        if branch_code: q["branch_code"] = branch_code
        q.update(_date_range_query(from_f, to_f))
        ccc_docs = list(db["hospital_cashcountercollection"].find(q))

        by_cat = {}
        for r in ccc_docs:
            by_cat.setdefault(r.get("billing_category"), []).append(r)

        billing_nums = list(set(
            r["bill_number"] for r in by_cat.get("Billing", []) + by_cat.get("Registration", []) + by_cat.get("RegistrationBills", [])
            if r.get("bill_number")
        ))
        pharmacy_nums = list(set(
            r["bill_number"] for r in by_cat.get("OPPharmacyBills", []) + by_cat.get("Pharmacy", []) + by_cat.get("PharmacyBills", [])
            if r.get("bill_number")
        ))
        discharge_nums = list(set(
            r["bill_number"] for r in by_cat.get("Discharge", []) + by_cat.get("DischargeBills", [])
            if r.get("bill_number")
        ))

        billing_docs   = list(db["hospital_billing"].find({"bill_number": {"$in": billing_nums}}))
        pharmacy_docs  = list(db["hospital_pharmacybilling"].find({"bill_no": {"$in": pharmacy_nums}}))
        discharge_docs = list(db["hospital_dischargebilling"].find({"bill_no": {"$in": discharge_nums}}))

        day_map = {}

        def bucket(day_str):
            return day_map.setdefault(day_str, {"date": day_str, "cash_in": 0.0, "cash_out": 0.0, "by_source": {}})

        def add_in(dt, amount, source):
            d = _parse_date(dt)
            if not d or amount <= 0: return
            b = bucket(d.isoformat())
            b["cash_in"] += amount
            b["by_source"][source] = b["by_source"].get(source, 0) + amount

        for d in billing_docs:
            if (d.get("payment_method") or "").strip().lower() == "cash":
                add_in(d.get("billed_date"), _to_float(d.get("total_fees")), "Registration (OP)")

        for d in pharmacy_docs:
            if (d.get("payment_mode") or "").strip().lower() == "cash":
                add_in(d.get("bill_date"), _to_float(d.get("net_amount")), "Pharmacy")

        for d in discharge_docs:
            pd_ = d.get("payment_details") or {}
            mode = (pd_.get("method") or "").strip().lower()
            if mode == "cash":
                add_in(d.get("bill_date"), _to_float(pd_.get("Paid_amount")), "Discharge")
            elif mode == "multiple payment":
                cash_amt = sum(
                    _to_float(b.get("Paid_amount")) for b in (pd_.get("breakdown") or [])
                    if isinstance(b, dict) and (b.get("method") or "").strip().lower() == "cash"
                )
                add_in(d.get("bill_date"), cash_amt, "Discharge")

        client.close()

        # Cash Book — Receipt & Payment vouchers (Receipt = in, Payment = out)
        rp_qs = ReceiptAndPayment.objects.all()
        if from_f:
            f_date = _parse_date(from_f)
            if f_date: rp_qs = rp_qs.filter(voucher_date__gte=f_date)
        if to_f:
            t_date = _parse_date(to_f)
            if t_date: rp_qs = rp_qs.filter(voucher_date__lte=t_date)

        for r in rp_qs:
            if not r.voucher_date: continue
            b = bucket(r.voucher_date.isoformat())
            amt = _to_float(r.amount)
            if r.receipt_type == "Receipt":
                b["cash_in"] += amt
                head = r.account_head or "Misc Receipt"
                b["by_source"][head] = b["by_source"].get(head, 0) + amt
            elif r.receipt_type == "Payment":
                b["cash_out"] += amt

        rows = sorted(day_map.values(), key=lambda x: x["date"])
        for row in rows:
            row["net"] = row["cash_in"] - row["cash_out"]

        summary = {
            "total_cash_in": sum(r["cash_in"] for r in rows),
            "total_cash_out": sum(r["cash_out"] for r in rows),
        }
        summary["net"] = summary["total_cash_in"] - summary["total_cash_out"]

        return Response({"success": True, "data": rows, "summary": summary})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# Debit Bills Report
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def debit_bills_report(request):
    """
    'Debit Bills' — this system has no separate debit-note document, so this
    report surfaces bill edits that INCREASED the billed amount (the inverse
    of a credit/refund), sourced from Billing.edit_history.
    """
    try:
        from_f = request.GET.get("from_date")
        to_f   = request.GET.get("to_date")
        f_date = _parse_date(from_f) if from_f else None
        t_date = _parse_date(to_f) if to_f else None

        amount_fields = {"consulting_fee", "registration_fee", "total_fees"}
        records = list(Billing.objects.exclude(edit_history=[]).exclude(edit_history__isnull=True))

        rows = []
        patient_ids = set()
        for bill in records:
            history = bill.edit_history if isinstance(bill.edit_history, list) else []
            for entry in history:
                if not isinstance(entry, dict): continue
                changes = entry.get("changes") or {}
                entry_date = _parse_date(entry.get("date"))
                if f_date and entry_date and entry_date < f_date: continue
                if t_date and entry_date and entry_date > t_date: continue

                for field, diff in changes.items():
                    if field not in amount_fields or not isinstance(diff, dict):
                        continue
                    try:
                        old_val = float(diff.get("old") or 0)
                        new_val = float(diff.get("new") or 0)
                    except (TypeError, ValueError):
                        continue
                    if new_val <= old_val:
                        continue  # only amount increases count as a debit

                    patient_ids.add(bill.patient_id)
                    rows.append({
                        "bill_number": bill.bill_number,
                        "patient_id": bill.patient_id,
                        "field": field,
                        "old_amount": old_val,
                        "new_amount": new_val,
                        "debit_amount": new_val - old_val,
                        "edited_by": entry.get("user"),
                        "edited_date": entry.get("date"),
                    })

        patients = {p.id: p for p in Patient.objects.filter(id__in=patient_ids)}

        employee_ids = {r["edited_by"] for r in rows if r["edited_by"]}
        employee_map = {}
        if employee_ids:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            try:
                profiles = client["Global"]["backend_diagnostics_profile"].find(
                    {"employeeId": {"$in": list(employee_ids)}}, {"employeeId": 1, "employeeName": 1}
                )
                employee_map = {str(p["employeeId"]): p.get("employeeName", "") for p in profiles}
            except Exception:
                pass
            client.close()

        if not rows:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            db = client["HMS"]
            dch_docs = list(db["hospital_dischargebilling"].find({}))
            client.close()

            uhids = list(set(d.get("uhid") for d in dch_docs if d.get("uhid")))
            patient_map = {p.uhid: f"{p.firstName} {p.lastName}".strip() for p in Patient.objects.filter(uhid__in=uhids)}

            for d in dch_docs:
                b_date = _parse_date(d.get("bill_date") or d.get("created_date"))
                if f_date and b_date and b_date < f_date: continue
                if t_date and b_date and b_date > t_date: continue

                pd = d.get("payment_details") or {}
                tot = _to_float(d.get("net_amount") or d.get("total_amount"))
                paid = _to_float(pd.get("Paid_amount") or d.get("paid_amount"))
                pending = _to_float(d.get("pending_amount") or (tot - paid))

                if tot > 0:
                    rows.append({
                        "bill_number": d.get("bill_no") or d.get("estimate_number") or "N/A",
                        "uhid": d.get("uhid", ""),
                        "patient_name": patient_map.get(d.get("uhid"), "Patient"),
                        "field": "Discharge Debit",
                        "old_amount": paid,
                        "new_amount": tot,
                        "debit_amount": pending if pending > 0 else tot,
                        "edited_by": d.get("CashierID") or d.get("created_by") or "",
                        "edited_by_name": d.get("CashierID") or "Staff",
                        "edited_date": _format_dt(d.get("bill_date") or d.get("created_date")),
                    })

        rows.sort(key=lambda x: x["edited_date"] or "", reverse=True)
        summary = {
            "count": len(rows),
            "total_debit_amount": sum(r["debit_amount"] for r in rows),
        }

        return Response({"success": True, "data": rows, "summary": summary})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# Audit Report (cross-record billing edit history)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def audit_report(request):
    """
    Cross-record audit trail of billing edits. There's no centralized audit
    log in this system — each billing type tracks its own edit history in a
    different shape, so this unions four of them into one report:
    Registration Billing (Billing.edit_history), Pharmacy Billing
    (medicine_particulars[].edit_history), Sales Return (same pattern), and
    Investigation Billing (hospital_investbilling 'history' array).
    """
    try:
        from_f = request.GET.get("from_date")
        to_f   = request.GET.get("to_date")
        f_date = _parse_date(from_f) if from_f else None
        t_date = _parse_date(to_f) if to_f else None

        def in_range(d):
            if f_date and d and d < f_date: return False
            if t_date and d and d > t_date: return False
            return True

        rows = []
        employee_ids = set()

        # 1. Registration Billing
        for bill in Billing.objects.exclude(edit_history=[]).exclude(edit_history__isnull=True):
            for entry in (bill.edit_history or []):
                if not isinstance(entry, dict): continue
                d = _parse_date(entry.get("date"))
                if not in_range(d): continue
                for field, diff in (entry.get("changes") or {}).items():
                    if not isinstance(diff, dict): continue
                    employee_ids.add(entry.get("user"))
                    rows.append({
                        "source": "Registration Billing", "record_no": bill.bill_number, "uhid": None,
                        "description": f"{field} changed", "old_value": str(diff.get("old", "")),
                        "new_value": str(diff.get("new", "")), "edited_by": entry.get("user"),
                        "edited_date": entry.get("date"),
                    })

        # 2. Pharmacy Billing (per medicine item qty edits)
        item_ids = set()
        pharmacy_events = []
        for bill in PharmacyBilling.objects.all():
            meds = bill.medicine_particulars if isinstance(bill.medicine_particulars, list) else []
            for med in meds:
                if not isinstance(med, dict): continue
                for entry in (med.get("edit_history") or []):
                    if not isinstance(entry, dict): continue
                    ts = entry.get("timestamp")
                    d = _parse_date(ts)
                    if not in_range(d): continue
                    try:
                        iid = int(med.get("item_id"))
                        item_ids.add(iid)
                    except (TypeError, ValueError):
                        iid = None
                    employee_ids.add(entry.get("edited_by"))
                    pharmacy_events.append((bill.bill_no, bill.uhid, iid, entry))

        item_name_map = {i.item_id: i.item_name for i in PharmacyItem.objects.filter(item_id__in=item_ids)} if item_ids else {}
        for bill_no, uhid, iid, entry in pharmacy_events:
            item_name = item_name_map.get(iid, f"Item #{iid}" if iid else "Unknown item")
            action = entry.get("action", "")
            if action in ("qty_added", "qty_deleted"):
                old_v, new_v = entry.get("old_qty"), entry.get("new_qty")
            elif action == "medicine_added":
                old_v, new_v = None, entry.get("qty")
            elif action == "medicine_deleted":
                old_v, new_v = entry.get("qty_deleted"), None
            else:
                old_v, new_v = None, None
            rows.append({
                "source": "Pharmacy Billing", "record_no": bill_no, "uhid": uhid,
                "description": f"{action.replace('_', ' ').title()} — {item_name}",
                "old_value": str(old_v) if old_v is not None else "", "new_value": str(new_v) if new_v is not None else "",
                "edited_by": entry.get("edited_by"), "edited_date": entry.get("timestamp"),
            })

        # 3. Sales Return (same per-item edit_history pattern)
        for ret in SalesReturn.objects.all():
            meds = ret.medicine_particulars if isinstance(ret.medicine_particulars, list) else []
            for med in meds:
                if not isinstance(med, dict): continue
                for entry in (med.get("edit_history") or []):
                    if not isinstance(entry, dict): continue
                    d = _parse_date(entry.get("timestamp"))
                    if not in_range(d): continue
                    employee_ids.add(entry.get("edited_by"))
                    try:
                        iid = int(med.get("item_id"))
                    except (TypeError, ValueError):
                        iid = None
                    rows.append({
                        "source": "Sales Return", "record_no": ret.return_bill_no, "uhid": ret.uhid,
                        "description": f"{(entry.get('action') or 'Edited').replace('_', ' ').title()} — Item #{iid}" if iid else "Return item edited",
                        "old_value": str(entry.get("old_qty", "")), "new_value": str(entry.get("new_qty", "")),
                        "edited_by": entry.get("edited_by"), "edited_date": entry.get("timestamp"),
                    })

        # 4. Investigation Billing (raw Mongo 'history' array — old value only, no new value stored)
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]
        for doc in db["hospital_investbilling"].find({"history.0": {"$exists": True}}, {"investBillNo": 1, "uhid": 1, "history": 1}):
            for entry in (doc.get("history") or []):
                if not isinstance(entry, dict): continue
                d = _parse_date(entry.get("modified_date"))
                if not in_range(d): continue
                employee_ids.add(entry.get("modified_by"))
                for field, old_val in (entry.get("changes") or {}).items():
                    rows.append({
                        "source": "Investigation Billing", "record_no": doc.get("investBillNo"), "uhid": doc.get("uhid"),
                        "description": f"{field} changed" + (f" — {entry.get('editRemarks')}" if entry.get("editRemarks") else ""),
                        "old_value": str(old_val), "new_value": "(see current record)",
                        "edited_by": entry.get("modified_by"), "edited_date": entry.get("modified_date"),
                    })
        client.close()

        # Resolve employee names + patient names
        employee_map = {}
        if employee_ids:
            employee_ids.discard(None)
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            try:
                profiles = client["Global"]["backend_diagnostics_profile"].find(
                    {"employeeId": {"$in": list(employee_ids)}}, {"employeeId": 1, "employeeName": 1}
                )
                employee_map = {str(p["employeeId"]): p.get("employeeName", "") for p in profiles}
            except Exception:
                pass
            client.close()

        uhids = {r["uhid"] for r in rows if r.get("uhid")}
        patient_map = {
            p.uhid: f"{p.firstName} {p.lastName}".strip()
            for p in Patient.objects.filter(uhid__in=list(uhids))
        }

        for r in rows:
            r["edited_by_name"] = employee_map.get(str(r["edited_by"]), r["edited_by"] or "")
            r["patient_name"] = patient_map.get(r.get("uhid"), "") if r.get("uhid") else ""

        rows.sort(key=lambda x: x["edited_date"] or "", reverse=True)

        summary = {}
        for r in rows:
            summary[r["source"]] = summary.get(r["source"], 0) + 1

        return Response({"success": True, "data": rows, "summary": {"count": len(rows), "by_source": summary}})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# Sales Tax (GST) Register — Pharmacy OP/IP sales + returns
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def sales_tax_register(request):
    """
    GST Sales Tax Register for pharmacy OP/IP sales + sales returns.

    APPROXIMATION NOTICE: sale/return line items only store one opaque 'tax'
    number (no CGST/SGST rate breakdown persisted at sale time). This report
    re-joins each line's item_id+batch_number back to PharmacyStock's
    CURRENT CGST_Percentage/SGST_Percentage to estimate the rate-wise split.
    Older bills whose batch's tax rate has since changed will be inaccurate.

    Query params:
    - patient_type = 'all' | 'op' | 'ip' (default: all)
    - report_type  = 'all' | 'sales' | 'returns' (default: all)
    """
    try:
        from_f = request.GET.get("from_date")
        to_f   = request.GET.get("to_date")
        patient_type = (request.GET.get("patient_type") or "all").lower()
        report_type = (request.GET.get("report_type") or "all").lower()
        f_date = _parse_date(from_f) if from_f else None
        t_date = _parse_date(to_f) if to_f else None

        def in_range(d):
            if f_date and d and d < f_date: return False
            if t_date and d and d > t_date: return False
            return True

        sale_bills = list(PharmacyBilling.objects.filter(billing_status="Paid")) if report_type in ("all", "sales", "sale") else []
        returns = list(SalesReturn.objects.all()) if report_type in ("all", "returns", "return") else []
        return_bill_nos = {r.bill_no for r in returns if r.bill_no}
        orig_bill_map = {b.bill_no: b for b in PharmacyBilling.objects.filter(bill_no__in=return_bill_nos)} if return_bill_nos else {}

        item_ids = set()
        for b in sale_bills:
            for med in (b.medicine_particulars or []):
                if isinstance(med, dict) and med.get("item_id") is not None:
                    try: item_ids.add(int(med["item_id"]))
                    except (TypeError, ValueError): pass
        for r in returns:
            for med in (r.medicine_particulars or []):
                if isinstance(med, dict) and med.get("item_id") is not None:
                    try: item_ids.add(int(med["item_id"]))
                    except (TypeError, ValueError): pass

        rate_map = {}
        if item_ids:
            for s in PharmacyStock.objects.filter(item_id__in=item_ids):
                key = (str(s.item_id), str(s.batch_number))
                if key not in rate_map:
                    rate_map[key] = (_to_float(s.CGST_Percentage), _to_float(s.SGST_Percentage))

        item_name_map = {i.item_id: i.item_name for i in PharmacyItem.objects.filter(item_id__in=item_ids)} if item_ids else {}

        def tax_split(amount, cgst_pct, sgst_pct):
            total_rate = cgst_pct + sgst_pct
            if total_rate <= 0:
                return amount, 0.0, 0.0
            taxable = amount / (1 + total_rate / 100)
            return taxable, taxable * cgst_pct / 100, taxable * sgst_pct / 100

        sales_lines = []
        for b in sale_bills:
            d = _parse_date(b.bill_date)
            if not in_range(d): continue
            category = "IP" if b.inpatient_number else "OP"
            if patient_type in ("ip", "op") and category.lower() != patient_type: continue

            for med in (b.medicine_particulars or []):
                if not isinstance(med, dict): continue
                amount = _to_float(med.get("calculated_price"))
                if amount <= 0: continue
                try: iid = int(med.get("item_id"))
                except (TypeError, ValueError): iid = None
                cgst_pct, sgst_pct = rate_map.get((str(med.get("item_id")), str(med.get("batch_number") or "")), (0.0, 0.0))
                taxable, cgst_amt, sgst_amt = tax_split(amount, cgst_pct, sgst_pct)
                sales_lines.append({
                    "type": "Sale", "patient_type": category, "bill_no": b.bill_no,
                    "date": b.bill_date.isoformat() if b.bill_date else None,
                    "item_name": med.get("item_name") or item_name_map.get(iid, ""),
                    "batch_no": med.get("batch_number") or "",
                    "rate": round(cgst_pct + sgst_pct, 2),
                    "taxable_value": taxable, "cgst_amount": cgst_amt, "sgst_amount": sgst_amt,
                    "total_tax": cgst_amt + sgst_amt, "gross_amount": amount,
                })

        return_lines = []
        for r in returns:
            orig = orig_bill_map.get(r.bill_no)
            category = "IP" if (orig and orig.inpatient_number) else "OP"
            if patient_type in ("ip", "op") and category.lower() != patient_type: continue
            d = _parse_date(r.return_bill_date)
            if not in_range(d): continue

            for med in (r.medicine_particulars or []):
                if not isinstance(med, dict): continue
                amount = _to_float(med.get("return_amount"))
                if amount <= 0: continue
                try: iid = int(med.get("item_id"))
                except (TypeError, ValueError): iid = None
                cgst_pct, sgst_pct = rate_map.get((str(med.get("item_id")), str(med.get("batch_number") or "")), (0.0, 0.0))
                taxable, cgst_amt, sgst_amt = tax_split(amount, cgst_pct, sgst_pct)
                return_lines.append({
                    "type": "Return", "patient_type": category,
                    "bill_no": r.return_bill_no,
                    "orig_bill_no": r.bill_no or "—",
                    "date": r.return_bill_date.isoformat() if r.return_bill_date else None,
                    "item_name": item_name_map.get(iid, "") or med.get("item_name", ""),
                    "batch_no": med.get("batch_number") or "",
                    "rate": round(cgst_pct + sgst_pct, 2),
                    "taxable_value": taxable, "cgst_amount": cgst_amt, "sgst_amount": sgst_amt,
                    "total_tax": cgst_amt + sgst_amt, "gross_amount": amount,
                })

        # Calculate Sales Summary
        sales_rate_summary = {}
        for l in sales_lines:
            key = l["rate"]
            b = sales_rate_summary.setdefault(key, {"rate": key, "taxable_value": 0.0, "cgst_amount": 0.0, "sgst_amount": 0.0, "total_tax": 0.0, "gross_amount": 0.0, "count": 0})
            b["taxable_value"] += l["taxable_value"]
            b["cgst_amount"] += l["cgst_amount"]
            b["sgst_amount"] += l["sgst_amount"]
            b["total_tax"] += l["total_tax"]
            b["gross_amount"] += l["gross_amount"]
            b["count"] += 1

        sales_summary = {
            "count": len(sales_lines),
            "total_taxable_value": sum(l["taxable_value"] for l in sales_lines),
            "total_cgst": sum(l["cgst_amount"] for l in sales_lines),
            "total_sgst": sum(l["sgst_amount"] for l in sales_lines),
            "total_tax": sum(l["total_tax"] for l in sales_lines),
            "total_gross": sum(l["gross_amount"] for l in sales_lines),
            "rate_wise": sorted(sales_rate_summary.values(), key=lambda x: x["rate"]),
        }

        # Calculate Return Summary (positive magnitudes for Return Report)
        return_rate_summary = {}
        for l in return_lines:
            key = l["rate"]
            b = return_rate_summary.setdefault(key, {"rate": key, "taxable_value": 0.0, "cgst_amount": 0.0, "sgst_amount": 0.0, "total_tax": 0.0, "gross_amount": 0.0, "count": 0})
            b["taxable_value"] += l["taxable_value"]
            b["cgst_amount"] += l["cgst_amount"]
            b["sgst_amount"] += l["sgst_amount"]
            b["total_tax"] += l["total_tax"]
            b["gross_amount"] += l["gross_amount"]
            b["count"] += 1

        return_summary = {
            "count": len(return_lines),
            "total_taxable_value": sum(l["taxable_value"] for l in return_lines),
            "total_cgst": sum(l["cgst_amount"] for l in return_lines),
            "total_sgst": sum(l["sgst_amount"] for l in return_lines),
            "total_tax": sum(l["total_tax"] for l in return_lines),
            "total_gross": sum(l["gross_amount"] for l in return_lines),
            "rate_wise": sorted(return_rate_summary.values(), key=lambda x: x["rate"]),
        }

        # Calculate Net Consolidated Rate-wise & Summary
        all_rates = set(sales_rate_summary.keys()) | set(return_rate_summary.keys())
        net_rate_wise = []
        for rate in sorted(all_rates):
            s_data = sales_rate_summary.get(rate, {"taxable_value": 0.0, "cgst_amount": 0.0, "sgst_amount": 0.0, "total_tax": 0.0, "gross_amount": 0.0, "count": 0})
            r_data = return_rate_summary.get(rate, {"taxable_value": 0.0, "cgst_amount": 0.0, "sgst_amount": 0.0, "total_tax": 0.0, "gross_amount": 0.0, "count": 0})
            net_rate_wise.append({
                "rate": rate,
                "sales_taxable": s_data["taxable_value"],
                "sales_gross": s_data["gross_amount"],
                "return_taxable": r_data["taxable_value"],
                "return_gross": r_data["gross_amount"],
                "taxable_value": s_data["taxable_value"] - r_data["taxable_value"],
                "cgst_amount": s_data["cgst_amount"] - r_data["cgst_amount"],
                "sgst_amount": s_data["sgst_amount"] - r_data["sgst_amount"],
                "total_tax": s_data["total_tax"] - r_data["total_tax"],
                "gross_amount": s_data["gross_amount"] - r_data["gross_amount"],
            })

        net_summary = {
            "total_sales_taxable": sales_summary["total_taxable_value"],
            "total_sales_gross": sales_summary["total_gross"],
            "total_return_taxable": return_summary["total_taxable_value"],
            "total_return_gross": return_summary["total_gross"],
            "total_taxable_value": sales_summary["total_taxable_value"] - return_summary["total_taxable_value"],
            "total_cgst": sales_summary["total_cgst"] - return_summary["total_cgst"],
            "total_sgst": sales_summary["total_sgst"] - return_summary["total_sgst"],
            "total_tax": sales_summary["total_tax"] - return_summary["total_tax"],
            "total_gross": sales_summary["total_gross"] - return_summary["total_gross"],
            "rate_wise": net_rate_wise,
        }

        # Consolidated Lines with negative return amounts for consolidated table
        consolidated_return_lines = []
        for l in return_lines:
            consolidated_return_lines.append({
                **l,
                "taxable_value": -l["taxable_value"],
                "cgst_amount": -l["cgst_amount"],
                "sgst_amount": -l["sgst_amount"],
                "total_tax": -l["total_tax"],
                "gross_amount": -l["gross_amount"],
            })

        all_lines = sorted(sales_lines + consolidated_return_lines, key=lambda x: x["date"] or "", reverse=True)

        def build_daywise_register(lines, is_return=False):
            day_groups = {}
            for l in lines:
                if not l.get("date"):
                    continue
                try:
                    dt_str = str(l["date"])
                    if "T" in dt_str:
                        dt_obj = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    elif " " in dt_str:
                        dt_obj = datetime.strptime(dt_str[:19], "%Y-%m-%d %H:%M:%S")
                    else:
                        dt_obj = datetime.strptime(dt_str[:10], "%Y-%m-%d")
                    d_key = dt_obj.strftime("%Y-%m-%d")
                    d_display = dt_obj.strftime("%d/%m/%Y")
                except Exception:
                    d_key = str(l["date"])[:10]
                    d_display = d_key

                ptype = (l.get("patient_type") or "OP").upper()
                group_key = (d_key, ptype)

                if group_key not in day_groups:
                    bill_prefix = "RETURN " if is_return else ""
                    bill_name = f"PHARMACY {bill_prefix}{ptype} BILL (SH)"
                    day_groups[group_key] = {
                        "raw_date": d_key,
                        "bill_date": d_display,
                        "bill_name": bill_name,
                        "patient_type": ptype,
                        "bill_numbers": set(),
                        "exempted": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                        "rate_5": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                        "rate_12": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                        "rate_18": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                        "rate_28": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                        "total": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                    }

                entry = day_groups[group_key]
                if l.get("bill_no"):
                    entry["bill_numbers"].add(str(l["bill_no"]))

                rate = round(float(l.get("rate") or 0.0), 2)
                taxable = float(l.get("taxable_value") or 0.0)
                cgst = float(l.get("cgst_amount") or 0.0)
                sgst = float(l.get("sgst_amount") or 0.0)
                gross = float(l.get("gross_amount") or 0.0)

                # Assign to corresponding rate bucket
                if rate == 0 or rate < 2:
                    b = entry["exempted"]
                elif rate <= 6:
                    b = entry["rate_5"]
                elif rate <= 14:
                    b = entry["rate_12"]
                elif rate <= 20:
                    b = entry["rate_18"]
                else:
                    b = entry["rate_28"]

                b["taxable"] += taxable
                b["cgst"] += cgst
                b["sgst"] += sgst
                b["total"] += gross

                entry["total"]["taxable"] += taxable
                entry["total"]["cgst"] += cgst
                entry["total"]["sgst"] += sgst
                entry["total"]["total"] += gross

            result = []
            grand_total = {
                "exempted": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                "rate_5": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                "rate_12": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                "rate_18": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                "rate_28": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                "total": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
            }

            for k in sorted(day_groups.keys(), key=lambda x: (x[0], x[1])):
                item = day_groups[k]
                b_list = sorted(list(item["bill_numbers"]))
                if len(b_list) == 0:
                    bills_range = "—"
                elif len(b_list) == 1:
                    bills_range = b_list[0]
                else:
                    bills_range = f"{b_list[0]} - {b_list[-1]}"

                item["bills"] = bills_range
                item["bills_count"] = len(b_list)
                del item["bill_numbers"]

                for bucket in ["exempted", "rate_5", "rate_12", "rate_18", "rate_28", "total"]:
                    grand_total[bucket]["taxable"] += item[bucket]["taxable"]
                    grand_total[bucket]["cgst"] += item[bucket]["cgst"]
                    grand_total[bucket]["sgst"] += item[bucket]["sgst"]
                    grand_total[bucket]["total"] += item[bucket]["total"]

                result.append(item)

            return result, grand_total

        day_wise_sales, day_wise_sales_gt = build_daywise_register(sales_lines, is_return=False)
        day_wise_returns, day_wise_returns_gt = build_daywise_register(return_lines, is_return=True)

        # Build Day-wise Net Consolidated Register
        sales_day_map = {(row["raw_date"], row["patient_type"]): row for row in day_wise_sales}
        return_day_map = {(row["raw_date"], row["patient_type"]): row for row in day_wise_returns}
        all_day_keys = sorted(set(sales_day_map.keys()) | set(return_day_map.keys()), key=lambda x: (x[0], x[1]))

        day_wise_net = []
        day_wise_net_gt = {
            "exempted": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
            "rate_5": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
            "rate_12": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
            "rate_18": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
            "rate_28": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
            "total": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
        }

        for (d_key, ptype) in all_day_keys:
            s_row = sales_day_map.get((d_key, ptype))
            r_row = return_day_map.get((d_key, ptype))
            
            d_display = s_row["bill_date"] if s_row else (r_row["bill_date"] if r_row else d_key)
            bill_name = f"PHARMACY {ptype} BILL (SH)"
            bills_parts = []
            if s_row and s_row["bills"] != "—":
                bills_parts.append(s_row["bills"])
            if r_row and r_row["bills"] != "—":
                bills_parts.append(f"Ret: {r_row['bills']}")
            bills_range = " | ".join(bills_parts) if bills_parts else "—"

            net_row = {
                "raw_date": d_key,
                "bill_date": d_display,
                "bill_name": bill_name,
                "patient_type": ptype,
                "bills": bills_range,
                "exempted": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                "rate_5": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                "rate_12": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                "rate_18": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                "rate_28": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
                "total": {"taxable": 0.0, "sgst": 0.0, "cgst": 0.0, "total": 0.0},
            }

            for bucket in ["exempted", "rate_5", "rate_12", "rate_18", "rate_28", "total"]:
                s_taxable = s_row[bucket]["taxable"] if s_row else 0.0
                s_cgst = s_row[bucket]["cgst"] if s_row else 0.0
                s_sgst = s_row[bucket]["sgst"] if s_row else 0.0
                s_tot = s_row[bucket]["total"] if s_row else 0.0

                r_taxable = r_row[bucket]["taxable"] if r_row else 0.0
                r_cgst = r_row[bucket]["cgst"] if r_row else 0.0
                r_sgst = r_row[bucket]["sgst"] if r_row else 0.0
                r_tot = r_row[bucket]["total"] if r_row else 0.0

                net_row[bucket]["taxable"] = s_taxable - r_taxable
                net_row[bucket]["cgst"] = s_cgst - r_cgst
                net_row[bucket]["sgst"] = s_sgst - r_sgst
                net_row[bucket]["total"] = s_tot - r_tot

                day_wise_net_gt[bucket]["taxable"] += (s_taxable - r_taxable)
                day_wise_net_gt[bucket]["cgst"] += (s_cgst - r_cgst)
                day_wise_net_gt[bucket]["sgst"] += (s_sgst - r_sgst)
                day_wise_net_gt[bucket]["total"] += (s_tot - r_tot)

            day_wise_net.append(net_row)

        if report_type in ("returns", "return"):
            active_data = sorted(return_lines, key=lambda x: x["date"] or "", reverse=True)
            active_summary = return_summary
        elif report_type in ("sales", "sale"):
            active_data = sorted(sales_lines, key=lambda x: x["date"] or "", reverse=True)
            active_summary = sales_summary
        else:
            active_data = all_lines
            active_summary = net_summary

        return Response({
            "success": True,
            "data": active_data,
            "summary": active_summary,
            "sales_data": sorted(sales_lines, key=lambda x: x["date"] or "", reverse=True),
            "return_data": sorted(return_lines, key=lambda x: x["date"] or "", reverse=True),
            "consolidated_data": all_lines,
            "sales_summary": sales_summary,
            "return_summary": return_summary,
            "net_summary": net_summary,
            "day_wise_sales": day_wise_sales,
            "day_wise_sales_grand_total": day_wise_sales_gt,
            "day_wise_returns": day_wise_returns,
            "day_wise_returns_grand_total": day_wise_returns_gt,
            "day_wise_net": day_wise_net,
            "day_wise_net_grand_total": day_wise_net_gt,
            "is_approximate": True
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# Pharmacy Stock Report — IP vs OP consumption split
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def stock_report_ip_op(request):
    """
    Pharmacy stock CONSUMPTION split by IP vs OP for a date range.

    NOTE: PharmacyStock only tracks running balances (no per-transaction
    ledger linking a stock deduction back to a specific bill), so a true
    IP/OP split of stock BALANCES isn't possible in this system. This
    instead aggregates quantity + value sold per item from
    PharmacyBilling.medicine_particulars, grouped by whether the bill had
    an inpatient_number (IP) or not (OP) — i.e. a consumption report.
    """
    try:
        from_f = request.GET.get("from_date")
        to_f   = request.GET.get("to_date")
        f_date = _parse_date(from_f) if from_f else None
        t_date = _parse_date(to_f) if to_f else None

        def in_range(d):
            if f_date and d and d < f_date: return False
            if t_date and d and d > t_date: return False
            return True

        bills = list(PharmacyBilling.objects.filter(billing_status="Paid"))
        item_ids = set()
        for b in bills:
            for med in (b.medicine_particulars or []):
                if isinstance(med, dict) and med.get("item_id") is not None:
                    try: item_ids.add(int(med["item_id"]))
                    except (TypeError, ValueError): pass
        item_name_map = {i.item_id: i.item_name for i in PharmacyItem.objects.filter(item_id__in=item_ids)}

        item_stats = {}
        for b in bills:
            d = _parse_date(b.bill_date)
            if not in_range(d): continue
            is_ip = bool(b.inpatient_number)
            for med in (b.medicine_particulars or []):
                if not isinstance(med, dict): continue
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
                    med.get("count")
                )
                amt_val = (
                    med.get("calculated_price") if med.get("calculated_price") is not None else
                    med.get("amount") if med.get("amount") is not None else
                    med.get("total_amount") if med.get("total_amount") is not None else
                    med.get("net_amount") if med.get("net_amount") is not None else
                    med.get("total_price") if med.get("total_price") is not None else
                    med.get("price")
                )
                qty = _to_float(qty_val)
                amt = _to_float(amt_val)
                item_name = med.get("item_name") or med.get("itemName") or med.get("medicine_name") or item_name_map.get(iid) or f"Item #{iid}"
                bucket = item_stats.setdefault(iid, {
                    "item_id": iid, "item_name": item_name,
                    "ip_qty": 0.0, "ip_amount": 0.0, "op_qty": 0.0, "op_amount": 0.0,
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
            r["total_qty"] = round(tot_q, 2) if tot_q % 1 != 0 else int(tot_q)
            r["ip_qty"] = round(r["ip_qty"], 2) if r["ip_qty"] % 1 != 0 else int(r["ip_qty"])
            r["op_qty"] = round(r["op_qty"], 2) if r["op_qty"] % 1 != 0 else int(r["op_qty"])
            r["ip_amount"] = round(r["ip_amount"], 2)
            r["op_amount"] = round(r["op_amount"], 2)
            r["total_amount"] = round(tot_a, 2)
        rows.sort(key=lambda x: x["total_amount"], reverse=True)

        summary = {
            "total_ip_qty": round(sum(r["ip_qty"] for r in rows), 2),
            "total_ip_amount": round(sum(r["ip_amount"] for r in rows), 2),
            "total_op_qty": round(sum(r["op_qty"] for r in rows), 2),
            "total_op_amount": round(sum(r["op_amount"] for r in rows), 2),
        }

        return Response({"success": True, "data": rows, "summary": summary})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Patient Advance Details Report (IP Advance Report)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def patient_advance_details_report(request):
    """
    Returns patient advance details of currently admitted in-patients grouped by Floor/Ward,
    matching the formal Shanmuga Hospital IP Advance Report format.

    Query parameters:
    - as_on_date: YYYY-MM-DD (defaults to today)
    - floor: specific floor name or 'all'
    - has_advance: 'all' (default) | 'with_advance' | 'zero_advance'
    - customer_type: 'all' (default) | 'Insurance' | 'General' | 'Corporate'
    - search: search query on IP Number, Patient Name, Room Number, or Company Name
    """
    try:
        as_on_date_str = request.GET.get("as_on_date") or request.GET.get("date")
        floor_filter = (request.GET.get("floor") or "").strip()
        has_advance_filter = (request.GET.get("has_advance") or "all").strip().lower()
        customer_type_filter = (request.GET.get("customer_type") or "all").strip()
        search_query = (request.GET.get("search") or "").strip().lower()

        hospital_code, branch_code = _auth_scope(request)

        # Parse reference date
        ref_date = date.today()
        if as_on_date_str:
            parsed = _parse_date(as_on_date_str)
            if parsed:
                ref_date = parsed

        # Connect Mongo
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client[os.getenv("HMS_DB_NAME", "HMS")]

        # Query currently admitted patients
        adm_query = {
            "is_admitted": True,
            "is_discharged": False,
            "is_cancelled": {"$ne": True}
        }
        if hospital_code:
            adm_query["hospital_code"] = hospital_code
        if branch_code:
            adm_query["branch_code"] = branch_code

        admissions = list(db["hospital_admission"].find(adm_query))

        # Bulk fetch insurance providers, rooms, and patients
        ins_docs = list(db["hospital_insuranceprovider"].find({}, {"company_code": 1, "company_name": 1}))
        ins_map = {str(p.get("company_code")): p.get("company_name") for p in ins_docs if p.get("company_code")}

        room_docs = list(db["hospital_room"].find({}, {"room_number": 1, "nursing_station": 1, "floor": 1, "room_category": 1, "block": 1}))
        room_map = {str(r.get("room_number")): r for r in room_docs if r.get("room_number")}

        uhids = list({str(a.get("uhid")).strip() for a in admissions if a.get("uhid")})
        patient_docs = list(db["hospital_patient"].find({"uhid": {"$in": uhids}}))
        patient_map = {}
        for p in patient_docs:
            uhid_key = str(p.get("uhid")).strip().upper()
            full_name = " ".join(filter(None, [p.get("salutation"), p.get("firstName"), p.get("lastName")])).strip()
            patient_map[uhid_key] = full_name

        def get_floor_name(room_no, room_obj):
            if not room_no or room_no == "N/A":
                return "ALL FLOOR"
            
            r_str = str(room_no).strip().upper()
            nursing = (room_obj.get("nursing_station") or "").strip() if room_obj else ""
            n_upper = nursing.upper()
            r_cat = ((room_obj.get("room_category") or "") if room_obj else "").upper()
            flr = ((room_obj.get("floor") or "") if room_obj else "").upper()

            # Priority checks for floor categorization matching hospital layout
            if "FIRST SUIT" in n_upper or "FIRST FLOOR" in n_upper:
                return "1ST FLOOR"
            if "SECOND SUIT" in n_upper or "SECOND FLOOR" in n_upper:
                return "2ND FLOOR"
            if "THIRD FLOOR" in n_upper:
                return "3RD FLOOR"
            if "MICU" in n_upper or "MICU" in r_str:
                return "MICU"
            if "SICU" in n_upper or "SICU" in r_str:
                return "SICU"
            if "NICU" in n_upper or "NICU" in r_str:
                return "NICU"
            if "CHEMO" in n_upper or "CHEMO" in r_str:
                return "CHEMO"
            if "DAYCARE" in n_upper or "DAYCAR" in n_upper or "DAYCARE" in r_str or "DAYCAR" in r_str:
                return "DAYCAR"
            if "DIALYSIS" in n_upper or "DLS" in r_str:
                return "1ST FLOOR"  # Dialysis is on 1st Floor in Shanmuga Hospital
            if "RECOVERY" in n_upper:
                return "RECOVERY WARD"
            if "GW-A" in r_str or "GW" in r_str:
                return "GW-A"

            # Check room number prefix/ranges
            num_part = ''.join(c for c in r_str if c.isdigit())
            if num_part:
                num = int(num_part)
                if 100 <= num <= 399 or r_str.startswith("3") or r_str.startswith("SR-3") or r_str.startswith("TS-3"):
                    return "1ST FLOOR"
                elif 400 <= num <= 499 or r_str.startswith("4") or r_str.startswith("SR-4") or r_str.startswith("TS-4"):
                    return "2ND FLOOR"
                elif 500 <= num <= 599 or r_str.startswith("5") or r_str.startswith("SR-5") or r_str.startswith("TS-5"):
                    return "3RD FLOOR"

            if nursing:
                return nursing.upper()
            if flr:
                return flr
            return "ALL FLOOR"

        raw_records = []

        for adm in admissions:
            ip_num = str(adm.get("ipNumber") or "").strip()
            uhid_val = str(adm.get("uhid") or "").strip()
            p_name = patient_map.get(uhid_val.upper()) or "N/A"

            # Resolve admitting date
            adm_dt = adm.get("admissionDateTime")
            adm_date = None
            if isinstance(adm_dt, str):
                try:
                    adm_date = datetime.fromisoformat(adm_dt.replace('Z', '+00:00')).date()
                except:
                    adm_date = _parse_date(adm_dt)
            elif isinstance(adm_dt, datetime):
                adm_date = adm_dt.date()
            elif isinstance(adm_dt, date):
                adm_date = adm_dt

            if not adm_date:
                adm_date = ref_date

            # Calculate Length of Stay (No of days)
            no_of_days = max(0, (ref_date - adm_date).days)

            # Resolve active room
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
            floor_name = get_floor_name(room_no, room_obj)

            # Cumulative Advance Calculation
            adv_payments = adm.get("advance_payments") or []
            total_adv = 0.0
            advance_items = []
            if isinstance(adv_payments, list):
                for p in adv_payments:
                    if isinstance(p, dict):
                        is_active = p.get("is_advanceActive", True)
                        p_status = p.get("status", "Paid")
                        if is_active and p_status != "Cancelled" and not p.get("is_refund"):
                            amt = _to_float(p.get("advance_amount", 0))
                            total_adv += amt
                            advance_items.append({
                                "bill_no": p.get("bill_no") or "",
                                "advance_id": p.get("advance_id") or "",
                                "date": str(p.get("date") or p.get("bill_date") or "")[:10],
                                "amount": round(amt, 2),
                                "ip_advance": round(_to_float(p.get("ip_advance", 0)), 2),
                                "billing_advance": round(_to_float(p.get("billing_advance", 0)), 2),
                                "payment_mode": (p.get("payment_details", {}).get("method") if isinstance(p.get("payment_details"), dict) else p.get("payment_mode")) or "Cash",
                                "status": p_status
                            })

            total_adv = round(total_adv, 2)

            # Resolve Company Name
            comp_name = (
                adm.get("insurance_company") or
                ins_map.get(str(adm.get("company_code") or "")) or
                adm.get("packageName") or
                (adm.get("customer_type") if adm.get("customer_type") and adm.get("customer_type") != "General" else "") or
                ""
            ).strip()

            raw_records.append({
                "room": room_no,
                "ip_number": ip_num,
                "uhid": uhid_val,
                "patient_name": p_name,
                "admitting_date": adm_date.strftime("%d/%m/%Y"),
                "admitting_date_iso": adm_date.isoformat(),
                "no_of_days": no_of_days,
                "advance": total_adv,
                "company_name": comp_name,
                "floor": floor_name,
                "admitting_doctor": adm.get("admittingDoctor") or "",
                "customer_type": adm.get("customer_type") or "General",
                "advance_items": advance_items
            })

        # Apply Filters
        filtered_records = []
        for rec in raw_records:
            # Floor filter
            if floor_filter and floor_filter.lower() != "all" and floor_filter.lower() != "all floor":
                if rec["floor"].lower() != floor_filter.lower():
                    continue

            # Advance filter
            if has_advance_filter == "with_advance" and rec["advance"] <= 0:
                continue
            if has_advance_filter == "zero_advance" and rec["advance"] > 0:
                continue

            # Customer Type filter
            if customer_type_filter and customer_type_filter.lower() != "all":
                c_val = (rec["customer_type"] or "").lower()
                c_comp = (rec["company_name"] or "").lower()
                req_c = customer_type_filter.lower()
                if req_c == "general" and (rec["company_name"] or c_val not in ("general", "")):
                    continue
                elif req_c == "insurance" and not (rec["company_name"] or "insurance" in c_val):
                    continue
                elif req_c not in ("general", "insurance") and req_c not in c_val and req_c not in c_comp:
                    continue

            # Search query filter
            if search_query:
                combined_text = f"{rec['room']} {rec['ip_number']} {rec['uhid']} {rec['patient_name']} {rec['company_name']} {rec['floor']}".lower()
                if search_query not in combined_text:
                    continue

            filtered_records.append(rec)

        # Floor Ordering Definition
        floor_order = [
            "1ST FLOOR",
            "2ND FLOOR",
            "3RD FLOOR",
            "ALL FLOOR",
            "MICU",
            "SICU",
            "NICU",
            "CHEMO",
            "DAYCAR",
            "GW-A",
            "RECOVERY WARD"
        ]

        def get_floor_sort_key(flr):
            flr_u = flr.upper()
            try:
                return (0, floor_order.index(flr_u), flr_u)
            except ValueError:
                return (1, 999, flr_u)

        # Sort all records by Floor Order, then Room, then Admitting Date
        filtered_records.sort(key=lambda x: (
            get_floor_sort_key(x["floor"]),
            x["room"],
            x["admitting_date_iso"]
        ))

        # Assign sequential Sl-No
        for idx, r in enumerate(filtered_records, 1):
            r["sl_no"] = idx

        # Group data by Floor
        grouped_dict = {}
        for r in filtered_records:
            flr = r["floor"]
            if flr not in grouped_dict:
                grouped_dict[flr] = []
            grouped_dict[flr].append(r)

        grouped_data = []
        for flr in sorted(grouped_dict.keys(), key=get_floor_sort_key):
            flr_records = grouped_dict[flr]
            subtotal_adv = round(sum(item["advance"] for item in flr_records), 2)
            grouped_data.append({
                "floor": flr,
                "records": flr_records,
                "count": len(flr_records),
                "subtotal_advance": subtotal_adv
            })

        distinct_floors = sorted(list({r["floor"] for r in raw_records}), key=get_floor_sort_key)

        total_patients = len(filtered_records)
        total_with_advance = sum(1 for r in filtered_records if r["advance"] > 0)
        total_zero_advance = sum(1 for r in filtered_records if r["advance"] == 0)
        total_advance = round(sum(r["advance"] for r in filtered_records), 2)

        summary = {
            "total_patients": total_patients,
            "total_with_advance": total_with_advance,
            "total_zero_advance": total_zero_advance,
            "total_advance": total_advance,
            "as_on_date": ref_date.strftime("%d/%m/%Y"),
            "as_on_date_iso": ref_date.isoformat(),
        }

        return Response({
            "success": True,
            "data": filtered_records,
            "grouped_data": grouped_data,
            "floors_list": distinct_floors,
            "summary": summary
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Discount Bills Report
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def discount_bills_report(request):
    """
    Comprehensive Discount Bills Report across all hospital billing departments:
    - Pharmacy (OP & IP) with overall or item discounts
    - Investigation (Lab, CT, X-Ray, Scan, etc.) with concessions/discounts
    - Discharge settlements with concessions/discounts
    - Registration / Consultation billing if discounted
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        from_date_str = data.get("from_date")
        to_date_str = data.get("to_date")
        outlet_code = data.get("outlet_code") or data.get("outlet")
        category_filter = data.get("bill_type") or data.get("category")
        hospital_code, branch_code = _auth_scope(request)

        if not from_date_str:
            from_date_str = datetime.now().strftime("%Y-%m-%d")
        if not to_date_str:
            to_date_str = datetime.now().strftime("%Y-%m-%d")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

        f_d = _parse_date(from_date_str)
        t_d = _parse_date(to_date_str)

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        # Fetch bill type lookup for Investigation billing
        billtype_map = {}
        try:
            bt_list = list(db["hospital_billtype"].find({}, {"billTypeNo": 1, "bill_name": 1, "bill_type": 1}))
            for bt in bt_list:
                bt_no = bt.get("billTypeNo")
                bt_name = bt.get("bill_name")
                bt_id = bt.get("bill_type")
                if bt_no and bt_name:
                    billtype_map[str(bt_no).strip()] = str(bt_name).strip()
                if bt_id is not None and bt_name:
                    billtype_map[str(bt_id).strip()] = str(bt_name).strip()
        except Exception as e:
            print("Error fetching bill types in discount report:", e)

        raw_records = []

        # ── 1. PHARMACY BILLING ────────────────────────────────────────────────
        pharm_q = {
            "is_deleted": {"$ne": True}
        }
        if hospital_code: pharm_q["hospital_code"] = hospital_code
        if branch_code: pharm_q["branch_code"] = branch_code
        if outlet_code and str(outlet_code).strip().lower() != "all":
            pharm_q["outlet_code"] = outlet_code

        pharm_docs = list(db["hospital_pharmacybilling"].find(pharm_q))
        for doc in pharm_docs:
            b_date_val = doc.get("bill_date") or doc.get("created_date")
            b_date = _parse_date(b_date_val)
            if not b_date:
                continue
            if f_d and b_date < f_d:
                continue
            if t_d and b_date > t_d:
                continue

            # Calculate discount
            disc_amt = _to_float(doc.get("overall_discount_amount"))
            disc_val = _to_float(doc.get("overall_discount_value"))
            disc_type = str(doc.get("overall_discount_type") or "percent").lower()
            
            meds = doc.get("medicine_particulars") or []
            if isinstance(meds, str):
                try: meds = _json.loads(meds)
                except: meds = []

            item_disc_total = 0.0
            for m in meds:
                if isinstance(m, dict):
                    m_disc = _to_float(m.get("discount") or m.get("discount_amount") or m.get("discountAmount"))
                    item_disc_total += m_disc

            if disc_amt <= 0 and item_disc_total > 0:
                disc_amt = item_disc_total

            if disc_amt <= 0 and disc_val > 0:
                tot = _to_float(doc.get("total_amount"))
                if disc_type == "percent":
                    disc_amt = (tot * disc_val) / 100.0
                else:
                    disc_amt = disc_val

            if disc_amt <= 0:
                continue

            gross_amt = _to_float(doc.get("total_amount"))
            net_amt = _to_float(doc.get("net_amount"))
            if gross_amt <= 0:
                gross_amt = net_amt + disc_amt
            if net_amt <= 0:
                net_amt = max(0.0, gross_amt - disc_amt)

            disc_pct = disc_val if (disc_type == "percent" and disc_val > 0) else round((disc_amt / gross_amt * 100.0) if gross_amt > 0 else 0.0, 2)

            is_ip = bool(doc.get("inpatient_number") or doc.get("ip_no") or doc.get("admission_id"))
            category_name = "PHARMACY IP BILL (SH)" if is_ip else "PHARMACY OP BILL (SH)"
            b_date_str = b_date_val.strftime("%Y-%m-%d %H:%M:%S") if isinstance(b_date_val, datetime) else str(b_date_val)

            p_mode = doc.get("payment_mode") or doc.get("billing_mode") or "Cash"
            if isinstance(p_mode, dict):
                p_mode = p_mode.get("method") or "Cash"

            reason = doc.get("edit_reason") or doc.get("discount_reason") or doc.get("remarks") or ""

            raw_records.append({
                "id": f"PHARM-{doc.get('Bill_id') or doc.get('bill_no')}",
                "bill_no": str(doc.get("bill_no") or doc.get("estimate_no") or ""),
                "bill_date": b_date_str,
                "date": b_date.strftime("%Y-%m-%d"),
                "date_display": b_date.strftime("%d/%m/%Y"),
                "uhid": str(doc.get("uhid") or ""),
                "patient_name": str(doc.get("patientname") or ""),
                "ip_number": str(doc.get("inpatient_number") or ""),
                "room_no": str(doc.get("room_no") or ""),
                "doctor": str(doc.get("doctor_id") or doc.get("doctor") or ""),
                "category": category_name,
                "department": "Pharmacy",
                "gross_amount": round(gross_amt, 2),
                "discount_percent": round(disc_pct, 2),
                "discount_amount": round(disc_amt, 2),
                "net_amount": round(net_amt, 2),
                "reason": reason,
                "cashier_id": str(doc.get("cashier_id") or doc.get("created_by") or ""),
                "user": str(doc.get("cashier_id") or doc.get("created_by") or "STAFF").upper(),
                "payment_mode": p_mode,
                "outlet_code": str(doc.get("outlet_code") or "")
            })

        # ── 2. INVESTIGATION BILLING ──────────────────────────────────────────
        inv_q = {
            "is_active": {"$ne": False}
        }
        if hospital_code: inv_q["hospital_code"] = hospital_code
        if branch_code: inv_q["branch_code"] = branch_code
        if outlet_code and str(outlet_code).strip().lower() != "all":
            inv_q["outlet_code"] = outlet_code

        inv_docs = list(db["hospital_investbilling"].find(inv_q))
        for doc in inv_docs:
            b_date_val = doc.get("created_date") or doc.get("bill_date")
            b_date = _parse_date(b_date_val)
            if not b_date:
                continue
            if f_d and b_date < f_d:
                continue
            if t_d and b_date > t_d:
                continue

            disc_amt = _to_float(doc.get("discount"))
            disc_pct = _to_float(doc.get("discountPercent"))

            # Check line items if header discount is 0
            items = doc.get("item") or []
            if isinstance(items, str):
                try: items = _json.loads(items)
                except: items = []
            
            if disc_amt <= 0:
                item_disc_sum = 0.0
                for it in items:
                    if isinstance(it, dict):
                        it_disc = _to_float(it.get("discount") or it.get("discountAmount") or it.get("discount_amount"))
                        item_disc_sum += it_disc
                if item_disc_sum > 0:
                    disc_amt = item_disc_sum

            if disc_amt <= 0 and disc_pct > 0:
                tot = _to_float(doc.get("total"))
                disc_amt = (tot * disc_pct) / 100.0

            if disc_amt <= 0:
                continue

            gross_amt = _to_float(doc.get("total"))
            net_amt = _to_float(doc.get("finalPrice"))
            if gross_amt <= 0:
                gross_amt = net_amt + disc_amt
            if net_amt <= 0:
                net_amt = max(0.0, gross_amt - disc_amt)

            if disc_pct <= 0 and gross_amt > 0:
                disc_pct = round((disc_amt / gross_amt * 100.0), 2)

            # Bill type name
            bt_no = doc.get("billTypeNo") or doc.get("bill_type")
            bt_name = billtype_map.get(str(bt_no).strip()) if bt_no else None
            if not bt_name and items and isinstance(items, list) and len(items) > 0:
                first_it = items[0]
                if isinstance(first_it, dict):
                    it_bt_no = first_it.get("billTypeNo") or first_it.get("bill_type")
                    if it_bt_no:
                        bt_name = billtype_map.get(str(it_bt_no).strip())

            category_name = bt_name or "INVESTIGATION"
            if "(SH)" not in category_name and not category_name.endswith("BILL"):
                category_name = f"{category_name} (SH)"

            p_name = f"{doc.get('salutation', '')} {doc.get('firstName', '')} {doc.get('lastName', '')}".strip()
            if not p_name:
                p_name = str(doc.get("patient_name") or "")

            b_date_str = b_date_val.strftime("%Y-%m-%d %H:%M:%S") if isinstance(b_date_val, datetime) else str(b_date_val)
            reason = str(doc.get("discountRemarks") or doc.get("remarks") or doc.get("disc_reason") or "")

            p_mode = doc.get("paymentMethod") or doc.get("payment_method") or "Cash"
            if isinstance(p_mode, dict):
                p_mode = p_mode.get("method") or "Cash"

            raw_records.append({
                "id": f"INV-{doc.get('investBillNo') or doc.get('_id')}",
                "bill_no": str(doc.get("investBillNo") or ""),
                "bill_date": b_date_str,
                "date": b_date.strftime("%Y-%m-%d"),
                "date_display": b_date.strftime("%d/%m/%Y"),
                "uhid": str(doc.get("uhid") or ""),
                "patient_name": p_name,
                "ip_number": str(doc.get("ipNumber") or ""),
                "room_no": str(doc.get("roomNo") or ""),
                "doctor": str(doc.get("doctor") or doc.get("referredBy") or ""),
                "category": category_name,
                "department": "Investigation",
                "gross_amount": round(gross_amt, 2),
                "discount_percent": round(disc_pct, 2),
                "discount_amount": round(disc_amt, 2),
                "net_amount": round(net_amt, 2),
                "reason": reason,
                "cashier_id": str(doc.get("created_by") or doc.get("shiftno") or ""),
                "user": str(doc.get("created_by") or doc.get("shiftno") or "STAFF").upper(),
                "payment_mode": p_mode,
                "outlet_code": str(doc.get("outlet_code") or "")
            })

        # ── 3. DISCHARGE BILLING ──────────────────────────────────────────────
        disch_q = {
            "is_cancelled": {"$ne": True}
        }
        if hospital_code: disch_q["hospital_code"] = hospital_code
        if branch_code: disch_q["branch_code"] = branch_code

        disch_docs = list(db["hospital_dischargebilling"].find(disch_q))
        for doc in disch_docs:
            b_date_val = doc.get("bill_date") or doc.get("created_date")
            b_date = _parse_date(b_date_val)
            if not b_date:
                continue
            if f_d and b_date < f_d:
                continue
            if t_d and b_date > t_d:
                continue

            disc_amt = _to_float(doc.get("discount_amount") or doc.get("total_disc"))
            disc_pct = _to_float(doc.get("discount_percent"))

            if disc_amt <= 0 and disc_pct > 0:
                tot = _to_float(doc.get("total_amount"))
                disc_amt = (tot * disc_pct) / 100.0

            if disc_amt <= 0:
                continue

            gross_amt = _to_float(doc.get("total_amount"))
            net_amt = _to_float(doc.get("net_amount"))
            if gross_amt <= 0:
                gross_amt = net_amt + disc_amt
            if net_amt <= 0:
                net_amt = max(0.0, gross_amt - disc_amt)

            if disc_pct <= 0 and gross_amt > 0:
                disc_pct = round((disc_amt / gross_amt * 100.0), 2)

            b_date_str = b_date_val.strftime("%Y-%m-%d %H:%M:%S") if isinstance(b_date_val, datetime) else str(b_date_val)
            reason = str(doc.get("disc_reason") or doc.get("remarks") or "")

            pd = doc.get("payment_details") or {}
            if isinstance(pd, str):
                try: pd = _json.loads(pd)
                except: pd = {}
            p_mode = pd.get("method") or doc.get("payment_mode") or "Cash"

            raw_records.append({
                "id": f"DISCH-{doc.get('bill_no') or doc.get('discharge_id')}",
                "bill_no": str(doc.get("sh_bill_no") or doc.get("bill_no") or doc.get("estimate_number") or ""),
                "bill_date": b_date_str,
                "date": b_date.strftime("%Y-%m-%d"),
                "date_display": b_date.strftime("%d/%m/%Y"),
                "uhid": str(doc.get("uhid") or ""),
                "patient_name": str(doc.get("patient_name") or ""),
                "ip_number": str(doc.get("ip_number") or ""),
                "room_no": "",
                "doctor": "",
                "category": "DISCHARGE BILL",
                "department": "Discharge",
                "gross_amount": round(gross_amt, 2),
                "discount_percent": round(disc_pct, 2),
                "discount_amount": round(disc_amt, 2),
                "net_amount": round(net_amt, 2),
                "reason": reason,
                "cashier_id": str(doc.get("created_by") or doc.get("CashierID") or ""),
                "user": str(doc.get("created_by") or doc.get("CashierID") or "STAFF").upper(),
                "payment_mode": p_mode,
                "outlet_code": str(doc.get("outlet_code") or "")
            })

        # ── 4. RESOLVE PATIENT & CASHIER & ADMISSION DETAILS ─────────────────
        uhids = list(set([r["uhid"] for r in raw_records if r.get("uhid")]))
        patient_map = {}
        if uhids:
            try:
                for p in db["hospital_patient"].find({"uhid": {"$in": uhids}}, {"uhid": 1, "firstName": 1, "lastName": 1, "doctor_id": 1}):
                    patient_map[p["uhid"]] = {
                        "name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                        "doctor": p.get("doctor_id", "")
                    }
            except Exception as e:
                print("Patient fetch error in discount report:", e)

        # Lookup admissions for IP Room / Patient info if missing
        ip_nums = list(set([r["ip_number"] for r in raw_records if r.get("ip_number")]))
        admission_map = {}
        if ip_nums:
            try:
                for adm in db["hospital_admission"].find({"$or": [{"ipNumber": {"$in": ip_nums}}, {"ip_number": {"$in": ip_nums}}]}):
                    ip_k = adm.get("ipNumber") or adm.get("ip_number") or adm.get("ip_no")
                    if ip_k:
                        room_details = adm.get("room_details") or []
                        active_rooms = [rm for rm in room_details if rm.get("is_roomActive") in (True, "True", "true", 1, "1")]
                        r_no = (active_rooms[-1] if active_rooms else (room_details[-1] if room_details else {})).get("roomNo") or ""
                        admission_map[ip_k] = {
                            "patient_name": adm.get("patient_name") or adm.get("patientname") or "",
                            "doctor": adm.get("doctor") or adm.get("primary_doctor") or "",
                            "room_no": r_no
                        }
            except Exception as e:
                print("Admission fetch error in discount report:", e)

        # Cashier names lookup from Global DB
        cashier_ids = list(set([r["cashier_id"] for r in raw_records if r.get("cashier_id")]))
        cashier_name_map = {}
        try:
            g_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            g_db = g_client['Global']
            profiles = list(g_db['backend_diagnostics_profile'].find(
                {"employeeId": {"$in": cashier_ids}},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            ))
            cashier_name_map = {p['employeeId']: p['employeeName'] for p in profiles}
            g_client.close()
        except:
            pass

        # Apply mapped names
        for r in raw_records:
            if not r["patient_name"] or r["patient_name"] == "N/A":
                p_info = patient_map.get(r["uhid"])
                if p_info and p_info.get("name"):
                    r["patient_name"] = p_info["name"]
                elif r["ip_number"] and r["ip_number"] in admission_map:
                    r["patient_name"] = admission_map[r["ip_number"]].get("patient_name") or "Patient"

            if not r["doctor"] or r["doctor"] == "N/A":
                if r["ip_number"] and r["ip_number"] in admission_map:
                    r["doctor"] = admission_map[r["ip_number"]].get("doctor") or ""
                elif r["uhid"] and r["uhid"] in patient_map:
                    r["doctor"] = patient_map[r["uhid"]].get("doctor") or ""

            if not r["room_no"] and r["ip_number"] and r["ip_number"] in admission_map:
                r["room_no"] = admission_map[r["ip_number"]].get("room_no") or ""

            if r.get("cashier_id") and r["cashier_id"] in cashier_name_map:
                r["user"] = cashier_name_map[r["cashier_id"]].upper()

        client.close()

        # ── 5. FILTERING (Category / Bill Type) ───────────────────────────────
        filtered = []
        for r in raw_records:
            if category_filter and str(category_filter).strip().lower() not in ("all", ""):
                cf_norm = str(category_filter).replace(" ", "").replace("(SH)", "").lower()
                cat_norm = str(r["category"]).replace(" ", "").replace("(SH)", "").lower()
                dept_norm = str(r.get("department", "")).replace(" ", "").lower()
                if cf_norm not in cat_norm and cf_norm not in dept_norm:
                    continue
            filtered.append(r)

        # Sort by date desc, bill_no desc
        filtered.sort(key=lambda x: (x["date"], x["bill_date"] or ""), reverse=True)

        # ── 6. SUMMARY & GROUPED BREAKDOWNS ───────────────────────────────────
        total_discount_amount = sum(r["discount_amount"] for r in filtered)
        total_gross_amount = sum(r["gross_amount"] for r in filtered)
        total_net_amount = sum(r["net_amount"] for r in filtered)
        count = len(filtered)
        avg_discount_pct = round((total_discount_amount / total_gross_amount * 100.0) if total_gross_amount > 0 else 0.0, 2)

        by_category = {}
        for r in filtered:
            cat = r["category"]
            if cat not in by_category:
                by_category[cat] = {
                    "category": cat,
                    "count": 0,
                    "gross_amount": 0.0,
                    "discount_amount": 0.0,
                    "net_amount": 0.0
                }
            by_category[cat]["count"] += 1
            by_category[cat]["gross_amount"] = round(by_category[cat]["gross_amount"] + r["gross_amount"], 2)
            by_category[cat]["discount_amount"] = round(by_category[cat]["discount_amount"] + r["discount_amount"], 2)
            by_category[cat]["net_amount"] = round(by_category[cat]["net_amount"] + r["net_amount"], 2)

        distinct_categories = sorted(list(set(r["category"] for r in raw_records)))

        summary = {
            "total_discount_amount": round(total_discount_amount, 2),
            "total_gross_amount": round(total_gross_amount, 2),
            "total_net_amount": round(total_net_amount, 2),
            "count": count,
            "total_bills_count": count,
            "avg_discount_percent": avg_discount_pct,
            "by_category": by_category,
            "categories_list": distinct_categories
        }

        return Response({
            "success": True,
            "summary": summary,
            "data": filtered
        })

    except Exception as e:
        import traceback
        print("Discount Bills Report Error:", str(e))
        print(traceback.format_exc())
        return Response({"success": False, "message": str(e)}, status=500)


