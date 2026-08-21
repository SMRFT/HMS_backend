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
            try:
                # Handle "2026-05-11 10:00:00"
                return datetime.strptime(val.split(' ')[0], "%Y-%m-%d").date()
            except:
                return None
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
    try:
        bt_list = list(db["hospital_billtype"].find({}, {"billTypeNo": 1, "bill_name": 1}))
        for bt in bt_list:
            bt_no = bt.get("billTypeNo")
            bt_name = bt.get("bill_name")
            if bt_no and bt_name:
                billtype_map[bt_no] = bt_name
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
        return {d[field_name]: d for d in docs if field_name in d}

    # 1. OPPharmacyBills -> hospital_pharmacybilling (bill_no)
    pharmacy_bills = by_category.get("OPPharmacyBills", []) + by_category.get("Pharmacy", []) + by_category.get("PharmacyBills", [])
    pharmacy_nums = list(set([r["bill_number"] for r in pharmacy_bills]))
    pharmacy_map = fetch_docs("hospital_pharmacybilling", "bill_no", pharmacy_nums)

    # 2. Investigation -> hospital_investbilling (investBillNo)
    invest_bills = by_category.get("Investigation", []) + by_category.get("InvestigationBills", [])
    invest_nums = list(set([r["bill_number"] for r in invest_bills]))
    invest_map = fetch_docs("hospital_investbilling", "investBillNo", invest_nums)

    # 3. Billing -> hospital_billing (bill_number)
    billing_bills = by_category.get("Billing", []) + by_category.get("Registration", []) + by_category.get("RegistrationBills", [])
    billing_nums = list(set([r["bill_number"] for r in billing_bills]))
    billing_map = fetch_docs("hospital_billing", "bill_number", billing_nums)

    # 4. Discharge -> hospital_dischargebilling (bill_no)
    discharge_bills = by_category.get("Discharge", []) + by_category.get("DischargeBills", [])
    discharge_nums = list(set([r["bill_number"] for r in discharge_bills]))
    discharge_map = fetch_docs("hospital_dischargebilling", "bill_no", discharge_nums)

    # 5. IPAdvance -> hospital_admission (advance_payments.bill_no)
    advance_bills = by_category.get("IPAdvance", []) + by_category.get("IPAdvanceBills", [])
    advance_nums = list(set([r["bill_number"] for r in advance_bills]))
    advance_map = {}
    if advance_nums:
        adms = list(db["hospital_admission"].find({"advance_payments.bill_no": {"$in": advance_nums}}))
        for adm in adms:
            pays = adm.get("advance_payments", [])
            for p in pays:
                b_no = p.get("bill_no")
                if b_no in advance_nums:
                    advance_map[b_no] = {
                        "admission": adm,
                        "payment": p
                    }

    # 6. Sales Return -> hospital_salesreturn (return_bill_no)
    sales_return_bills = by_category.get("Sales Return", []) + by_category.get("sales_return", [])
    sales_return_nums = list(set([r["bill_number"] for r in sales_return_bills]))
    sales_return_map = fetch_docs("hospital_salesreturn", "return_bill_no", sales_return_nums)

    # 7. Receipt / Payment -> hospital_receiptandpayment (voucher_no)
    rp_bills = by_category.get("Receipt", []) + by_category.get("Payment", [])
    rp_nums = list(set([r["bill_number"] for r in rp_bills]))
    rp_map = fetch_docs("hospital_receiptandpayment", "voucher_no", rp_nums)

    # Loop through each ccc record and enrich it
    for r in ccc_records:
        cat = r.get("billing_category")
        bill_no = r.get("bill_number")
        
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
            detail.update({
                "type": "Pharmacy",
                "type_name": "PHARMACY OP BILL (SH)",
                "uhid": d.get("uhid"),
                "net_amount": _to_float(d.get("net_amount")),
                "display_amount": _to_float(d.get("net_amount")),
                "payment_mode": d.get("payment_mode") or d.get("payment_method") or "Cash",
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
            
            detail.update({
                "type": "Investigation",
                "type_name": display_type,
                "uhid": d.get("uhid"),
                "net_amount": _to_float(d.get("finalPrice") or d.get("total")),
                "display_amount": _to_float(d.get("finalPrice") or d.get("total")),
                "payment_mode": d.get("paymentMethod") or d.get("payment_method") or "Cash",
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
                "payment_mode": d.get("payment_mode") or "Cash",
                "items": d.get("items") or []
            })
            
        elif cat in ["Discharge", "DischargeBills"] and bill_no in discharge_map:
            d = discharge_map[bill_no]
            detail.update({
                "type": "Discharge",
                "type_name": "DISCHARGE",
                "uhid": d.get("uhid"),
                "net_amount": _to_float(d.get("net_amount")),
                "display_amount": _to_float(d.get("net_amount")),
                "payment_mode": d.get("payment_mode") or "Cash",
                "items": d.get("items") or []
            })
            
        elif cat in ["IPAdvance", "IPAdvanceBills"] and bill_no in advance_map:
            d = advance_map[bill_no]
            adm = d["admission"]
            pay = d["payment"]
            detail.update({
                "type": "IPAdvance",
                "type_name": "ADVANCE",
                "uhid": adm.get("uhid"),
                "net_amount": _to_float(pay.get("amount")),
                "display_amount": _to_float(pay.get("amount")),
                "payment_mode": pay.get("payment_details", {}).get("method", "Cash"),
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
    Queries hospital_cashcountercollection first.

    Extra query params:
    - payment_mode: 'Cash' | 'Card' | 'Cheque' | 'Multiple Payment' (omit = all)
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

        # Connect MongoDB to query hospital_cashcountercollection first
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        q = {"billing_category": {"$in": ["Discharge", "DischargeBills", "discharge"]}}
        if hospital_code: q["hospital_code"] = hospital_code
        if branch_code: q["branch_code"] = branch_code
        if from_f:
            f_date = _parse_date(from_f)
            if f_date:
                f_dt = datetime.combine(f_date, datetime.min.time())
                q.setdefault("created_date", {})["$gte"] = f_dt
        if to_f:
            t_date = _parse_date(to_f)
            if t_date:
                t_dt = datetime.combine(t_date, datetime.max.time())
                q.setdefault("created_date", {})["$lte"] = t_dt

        ccc_docs = list(db["hospital_cashcountercollection"].find(q))
        bill_numbers = list(set([doc["bill_number"] for doc in ccc_docs if doc.get("bill_number")]))

        if bill_numbers:
            raw_discharge_docs = list(db["hospital_dischargebilling"].find(
                {"bill_no": {"$in": bill_numbers}},
                {"bill_no": 1, "payment_details": 1, "CashierID": 1}
            ))
            all_records = list(DischargeBilling.objects.filter(bill_no__in=bill_numbers))
        else:
            raw_discharge_docs = list(db["hospital_dischargebilling"].find(
                {},
                {"bill_no": 1, "payment_details": 1, "CashierID": 1}
            ))
            all_records = list(DischargeBilling.objects.all())
            if from_f:
                f_d = _parse_date(from_f)
                if f_d: all_records = [r for r in all_records if r.bill_date and _parse_date(r.bill_date) >= f_d]
            if to_f:
                t_d = _parse_date(to_f)
                if t_d: all_records = [r for r in all_records if r.bill_date and _parse_date(r.bill_date) <= t_d]

        payment_mode_map = {
            d.get("bill_no"): (d.get("payment_details") or {}).get("method", "Cash")
            for d in raw_discharge_docs if d.get("bill_no")
        }
        cashier_map = {
            d.get("bill_no"): d.get("CashierID")
            for d in raw_discharge_docs if d.get("bill_no")
        }

        # Admission lookup for insurance detection, room, and admission date.
        # insuranceCompanyName is a raw Mongo field not declared on the Admission
        # model, so this is read via pymongo rather than the ORM.
        ip_numbers = list({r.ip_number for r in all_records if r.ip_number})
        admission_map = {}
        if ip_numbers:
            for a in db["hospital_admission"].find({"$or": [{"ipNumber": {"$in": ip_numbers}}, {"ip_number": {"$in": ip_numbers}}]}):
                ip_k = a.get("ipNumber") or a.get("ip_number") or a.get("ip_no")
                if ip_k:
                    admission_map[ip_k] = a

        client.close()

        filtered = []

        for obj in all_records:
            if not obj.is_active: continue
            if status_f and obj.status != status_f: continue

            payment_mode = payment_mode_map.get(obj.bill_no, "Cash")
            if payment_mode_f and payment_mode.lower() != payment_mode_f.lower():
                continue

            has_discount = _to_float(obj.total_disc) > 0
            if discount_only and not has_discount:
                continue

            admission = admission_map.get(obj.ip_number, {})
            insurance_company = admission.get("insuranceCompanyName")

            # Build patient details
            patient_details = {}
            p = None
            if obj.uhid:
                try:
                    p = Patient.objects.get(uhid=obj.uhid)
                    patient_details = {
                        "patient_name": f"{p.firstName} {p.lastName}".strip(),
                        "age": p.age,
                        "gender": p.gender,
                    }
                except Patient.DoesNotExist:
                    pass

            has_insurance = bool(
                insurance_company or
                (p and p.company_code) or
                (p and (getattr(p, 'customer_type', '') or '').lower() == 'insurance')
            )
            if insurance_f == "true" and not has_insurance:
                continue
            if insurance_f == "false" and has_insurance:
                continue

            room_details = admission.get("room_details") or []
            active_rooms = [rm for rm in room_details if rm.get("is_roomActive") in (True, "True", "true", 1, "1")]
            room_no = (active_rooms[-1] if active_rooms else (room_details[-1] if room_details else {})).get("roomNo")
            patient_details["room_no"] = room_no
            patient_details["admission_date"] = _format_dt(admission.get("admissionDateTime"))

            # Department-wise drill-down from the bill's own line items
            items = obj.items if isinstance(obj.items, list) else []
            dept_totals = {}
            for it in items:
                if not isinstance(it, dict): continue
                cat = it.get("category") or "Other"
                dept_totals[cat] = dept_totals.get(cat, 0) + _to_float(it.get("amount"))
            department_breakdown = [{"category": k, "amount": v} for k, v in dept_totals.items()]

            filtered.append({
                "id": obj.discharge_id,
                "bill_no": obj.bill_no,
                "estimate_number": obj.estimate_number,
                "uhid": obj.uhid,
                "ip_number": obj.ip_number,
                "branch_code": obj.branch_code,
                "bill_date": obj.bill_date.isoformat() if obj.bill_date else None,
                "total_amount": _to_float(obj.total_amount),
                "advance_amount": _to_float(obj.advance_amount),
                "net_amount": _to_float(obj.net_amount),
                "total_disc": _to_float(obj.total_disc),
                "has_discount": has_discount,
                "cashier_id": cashier_map.get(obj.bill_no),
                "status": obj.status,
                "patient_details": patient_details,
                "payment_mode": payment_mode,
                "has_insurance": has_insurance,
                "insurance_company": insurance_company or (p.company_code if p else None) or "",
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
# Advance Registration Report
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def advance_registration_report(request):
    """
    Dedicated reporting API for IP advance payments.
    Queries hospital_cashcountercollection first.
    """
    try:
        from_f = request.GET.get("from_date")
        to_f   = request.GET.get("to_date")
        is_insurance = request.GET.get("insurance") == "true"
        
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
        
        # Connect MongoDB to query hospital_cashcountercollection first
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]
        
        q = {"billing_category": {"$in": ["IPAdvance", "IPAdvanceBills", "advance"]}}
        if hospital_code: q["hospital_code"] = hospital_code
        if branch_code: q["branch_code"] = branch_code
        if from_f:
            f_date = _parse_date(from_f)
            if f_date:
                f_dt = datetime.combine(f_date, datetime.min.time())
                q.setdefault("created_date", {})["$gte"] = f_dt
        if to_f:
            t_date = _parse_date(to_f)
            if t_date:
                t_dt = datetime.combine(t_date, datetime.max.time())
                q.setdefault("created_date", {})["$lte"] = t_dt
                
        ccc_docs = list(db["hospital_cashcountercollection"].find(q))
        bill_numbers = list(set([doc["bill_number"] for doc in ccc_docs if doc.get("bill_number")]))
        
        if bill_numbers:
            admissions = list(db["hospital_admission"].find({"advance_payments.bill_no": {"$in": bill_numbers}}))
        else:
            admissions = list(db["hospital_admission"].find({"advance_payments": {"$exists": True, "$ne": []}}))
        client.close()
        
        uhids = list(set(a.get("uhid") for a in admissions if a.get('is_admissionActive', True) and a.get("uhid")))
        patients = Patient.objects.filter(uhid__in=uhids)
        patient_map = {p.uhid: p for p in patients}
        
        report_data = []
        f_d = _parse_date(from_f) if from_f else None
        t_d = _parse_date(to_f) if to_f else None

        for adm in admissions:
            if not adm.get('is_admissionActive', True): continue
            
            uhid = adm.get("uhid")
            p = patient_map.get(uhid)
            if not p: continue
            
            if is_insurance:
                has_insurance = (
                    p.company_code or 
                    adm.get('insuranceCompanyName') or 
                    getattr(p, 'customer_type', '').lower() == 'insurance'
                )
                if not has_insurance: continue
                
            payments = _parse_json(adm.get("advance_payments"))
            for pay in payments:
                if not isinstance(pay, dict) or pay.get('status') == 'Edited': continue
                
                bill_no = pay.get('bill_no') or pay.get('receipt_no') or pay.get('advance_id')
                if bill_numbers and bill_no and bill_no not in bill_numbers:
                    continue

                paid_dt_str = pay.get('paid_datetime') or pay.get('created_date') or pay.get('date')
                paid_d = _parse_date(paid_dt_str)
                if f_d and paid_d and paid_d < f_d: continue
                if t_d and paid_d and paid_d > t_d: continue
                
                paid_dt = pay.get('paid_datetime') or pay.get('created_date') or pay.get('date')
                ip_val = adm.get("ipNumber") or adm.get("ip_number") or adm.get("ip_no") or adm.get("inpatient_number") or ""
                p_name = f"{p.firstName} {p.lastName}".strip() if p else (adm.get("patient_name") or adm.get("patientname") or "Patient")
                report_data.append({
                    "ipNumber": ip_val,
                    "ip_number": ip_val,
                    "uhid": uhid,
                    "patient_name": p_name,
                    "age": getattr(p, "age", None) or adm.get("age"),
                    "gender": getattr(p, "gender", None) or adm.get("gender"),
                    "amount": _to_float(pay.get('amount') or pay.get('paid_amount') or pay.get('advance_amount')),
                    "paid_date": _format_dt(paid_dt),
                    "payment_mode": (pay.get('payment_details') or {}).get('method') or pay.get('payment_mode') or 'Cash',
                    "bill_no": bill_no,
                    "insurance_company": adm.get('insuranceCompanyName') or getattr(p, 'company_code', '') or 'N/A',
                    "admission_date": _format_dt(adm.get("admissionDateTime") or adm.get("created_date")),
                })
                
        report_data.sort(key=lambda x: x["paid_date"], reverse=True)
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

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def credit_card_report(request):
    """
    Lists every Card-mode collection across Registration (OP), Pharmacy,
    and Discharge billing for a date range. A 'Multiple Payment' discharge
    bill only contributes its card-only slice, not the full bill amount.
    """
    try:
        from_f = request.GET.get("from_date")
        to_f   = request.GET.get("to_date")
        hospital_code, branch_code = _auth_scope(request)

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        def _is_card(val):
            if not val: return False
            if isinstance(val, dict):
                val = val.get("method") or val.get("payment_mode") or ""
            s = str(val).strip().lower()
            return any(k in s for k in ["card", "credit", "debit", "pos", "swipe"])

        f_date = _parse_date(from_f) if from_f else None
        t_date = _parse_date(to_f) if to_f else None

        def in_date_range(d_val):
            d = _parse_date(d_val)
            if not d: return True
            if f_date and d < f_date: return False
            if t_date and d > t_date: return False
            return True

        # 1. Query hospital_cashcountercollection for any card payments
        q_ccc = {"$or": [
            {"payment_method": {"$regex": "card|credit|debit|pos|swipe", "$options": "i"}},
            {"payment_mode": {"$regex": "card|credit|debit|pos|swipe", "$options": "i"}}
        ]}
        if hospital_code: q_ccc["hospital_code"] = hospital_code
        if branch_code: q_ccc["branch_code"] = branch_code
        q_ccc.update(_date_range_query(from_f, to_f))

        ccc_docs = list(db["hospital_cashcountercollection"].find(q_ccc))

        # 2. Query billing, pharmacybilling, and dischargebilling directly for card transactions
        billing_docs = list(db["hospital_billing"].find({
            "$or": [
                {"payment_method": {"$regex": "card|credit|debit|pos|swipe", "$options": "i"}},
                {"payment_mode": {"$regex": "card|credit|debit|pos|swipe", "$options": "i"}}
            ]
        }))
        pharmacy_docs = list(db["hospital_pharmacybilling"].find({
            "$or": [
                {"payment_mode": {"$regex": "card|credit|debit|pos|swipe", "$options": "i"}},
                {"payment_method": {"$regex": "card|credit|debit|pos|swipe", "$options": "i"}}
            ]
        }))
        discharge_docs = list(db["hospital_dischargebilling"].find({
            "$or": [
                {"payment_details.method": {"$regex": "card|credit|debit|pos|swipe", "$options": "i"}},
                {"payment_mode": {"$regex": "card|credit|debit|pos|swipe", "$options": "i"}},
                {"payment_method": {"$regex": "card|credit|debit|pos|swipe", "$options": "i"}}
            ]
        }))

        seen_bills = set()
        uhids = set()
        rows = []

        for d in billing_docs:
            b_date = d.get("billed_date") or d.get("created_date")
            if not in_date_range(b_date): continue
            b_num = d.get("bill_number") or d.get("bill_no")
            if b_num and b_num in seen_bills: continue
            if b_num: seen_bills.add(b_num)

            amt = _to_float(d.get("total_fees") or d.get("amount") or d.get("paid_amount"))
            if amt <= 0: continue
            uhid = d.get("uhid")
            if uhid: uhids.add(uhid)
            p_name = d.get("patient_name") or d.get("patientname") or d.get("Patient_Name")
            rows.append({
                "type": "Registration (OP)", "bill_no": b_num or "N/A", "uhid": uhid or "",
                "patient_name": p_name,
                "bill_date": _format_dt(b_date), "amount": amt, "is_partial": False,
            })

        for d in pharmacy_docs:
            b_date = d.get("bill_date") or d.get("created_date")
            if not in_date_range(b_date): continue
            b_num = d.get("bill_no") or d.get("bill_number")
            if b_num and b_num in seen_bills: continue
            if b_num: seen_bills.add(b_num)

            amt = _to_float(d.get("net_amount") or d.get("total_amount") or d.get("paid_amount"))
            if amt <= 0: continue
            uhid = d.get("uhid")
            if uhid: uhids.add(uhid)
            p_name = d.get("patient_name") or d.get("patientname") or d.get("Patient_Name") or d.get("medicine_particulars", [{}])[0].get("patient_name")
            rows.append({
                "type": "Pharmacy", "bill_no": b_num or "N/A", "uhid": uhid or "",
                "patient_name": p_name,
                "bill_date": _format_dt(b_date), "amount": amt, "is_partial": False,
            })

        for d in discharge_docs:
            b_date = d.get("bill_date") or d.get("created_date")
            if not in_date_range(b_date): continue
            b_num = d.get("bill_no") or d.get("estimate_number")
            if b_num and b_num in seen_bills: continue
            if b_num: seen_bills.add(b_num)

            payment_details = d.get("payment_details") or {}
            card_amt = _card_amount(payment_details.get("method"), payment_details) or _to_float(d.get("paid_amount") or d.get("net_amount"))
            if card_amt <= 0: continue
            uhid = d.get("uhid")
            if uhid: uhids.add(uhid)
            p_name = d.get("patient_name") or d.get("patientname") or d.get("Patient_Name")
            rows.append({
                "type": "Discharge", "bill_no": b_num or "N/A", "uhid": uhid or "",
                "patient_name": p_name,
                "bill_date": _format_dt(b_date), "amount": card_amt,
                "is_partial": (payment_details.get("method") or "").strip().lower() == "multiple payment",
            })

        # Include remaining cashcountercollection card docs not captured above
        for d in ccc_docs:
            b_num = d.get("bill_number") or d.get("bill_no")
            if b_num and b_num in seen_bills: continue
            if b_num: seen_bills.add(b_num)

            mode = d.get("payment_method") or d.get("payment_mode")
            if not _is_card(mode): continue
            amt = _to_float(d.get("total_amount") or d.get("amount") or d.get("received_amount"))
            if amt <= 0: continue
            uhid = d.get("uhid") or d.get("patient_id")
            if uhid: uhids.add(uhid)
            rows.append({
                "type": d.get("billing_category") or "General",
                "bill_no": b_num or "N/A", "uhid": uhid or "",
                "patient_name": d.get("patient_name") or d.get("patientname"),
                "bill_date": _format_dt(d.get("created_date") or d.get("bill_date")),
                "amount": amt, "is_partial": False,
            })

        clean_uhids = [str(u) for u in uhids if u]
        patients = list(Patient.objects.filter(uhid__in=clean_uhids))
        patient_map = {str(p.uhid): f"{p.firstName} {p.lastName}".strip() for p in patients}

        for r in rows:
            if not r.get("patient_name"):
                u_str = str(r.get("uhid") or "")
                r["patient_name"] = patient_map.get(u_str) or (f"Patient #{u_str}" if u_str else "General / Cash Patient")

        client.close()

        rows.sort(key=lambda x: x["bill_date"] or "", reverse=True)
        summary = {
            "total_transactions": len(rows),
            "total_amount": sum(r["amount"] for r in rows),
            "by_type": {},
        }
        for r in rows:
            summary["by_type"][r["type"]] = summary["by_type"].get(r["type"], 0) + r["amount"]

        return Response({"success": True, "data": rows, "summary": summary})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# Date-wise Collection Summary (whole hospital)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def datewise_collection_summary(request):
    """
    Hospital-wide day-wise collection totals across every billing category
    (Registration, Pharmacy, Investigation, Discharge, IP Advance, Sales
    Return, Misc Receipts/Payments) — independent of cashier or shift.
    """
    try:
        from_f = request.GET.get("from_date")
        to_f   = request.GET.get("to_date")
        hospital_code, branch_code = _auth_scope(request)

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        q = {}
        if hospital_code: q["hospital_code"] = hospital_code
        if branch_code: q["branch_code"] = branch_code
        q.update(_date_range_query(from_f, to_f))

        ccc_docs = list(db["hospital_cashcountercollection"].find(q))
        enriched = fetch_detailed_billing_data(db, ccc_docs)
        client.close()

        day_map = {}
        for ccc, det in zip(ccc_docs, enriched):
            day = _parse_date(ccc.get("created_date"))
            if not day: continue
            day_str = day.isoformat()
            bucket = day_map.setdefault(day_str, {"date": day_str, "total": 0.0, "by_type": {}})
            amt = det.get("display_amount") or 0
            bucket["total"] += amt
            t = det.get("type") or "Other"
            bucket["by_type"][t] = bucket["by_type"].get(t, 0) + amt

        rows = sorted(day_map.values(), key=lambda x: x["date"])
        grand_total = sum(r["total"] for r in rows)

        return Response({"success": True, "data": rows, "grand_total": grand_total})
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

    Query params: patient_type = 'op' | 'ip' (default: all)
    """
    try:
        from_f = request.GET.get("from_date")
        to_f   = request.GET.get("to_date")
        patient_type = (request.GET.get("patient_type") or "all").lower()
        f_date = _parse_date(from_f) if from_f else None
        t_date = _parse_date(to_f) if to_f else None

        def in_range(d):
            if f_date and d and d < f_date: return False
            if t_date and d and d > t_date: return False
            return True

        sale_bills = list(PharmacyBilling.objects.filter(billing_status="Paid"))
        returns = list(SalesReturn.objects.all())
        return_bill_nos = {r.bill_no for r in returns if r.bill_no}
        orig_bill_map = {b.bill_no: b for b in PharmacyBilling.objects.filter(bill_no__in=return_bill_nos)}

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
        for s in PharmacyStock.objects.filter(item_id__in=item_ids):
            key = (str(s.item_id), str(s.batch_number))
            if key not in rate_map:
                rate_map[key] = (_to_float(s.CGST_Percentage), _to_float(s.SGST_Percentage))

        item_name_map = {i.item_id: i.item_name for i in PharmacyItem.objects.filter(item_id__in=item_ids)}

        def tax_split(amount, cgst_pct, sgst_pct):
            total_rate = cgst_pct + sgst_pct
            if total_rate <= 0:
                return amount, 0.0, 0.0
            taxable = amount / (1 + total_rate / 100)
            return taxable, taxable * cgst_pct / 100, taxable * sgst_pct / 100

        lines = []

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
                lines.append({
                    "type": "Sale", "patient_type": category, "bill_no": b.bill_no,
                    "date": b.bill_date.isoformat() if b.bill_date else None,
                    "item_name": med.get("item_name") or item_name_map.get(iid, ""),
                    "rate": round(cgst_pct + sgst_pct, 2),
                    "taxable_value": taxable, "cgst_amount": cgst_amt, "sgst_amount": sgst_amt,
                    "total_tax": cgst_amt + sgst_amt, "gross_amount": amount,
                })

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
                lines.append({
                    "type": "Return", "patient_type": category, "bill_no": r.return_bill_no,
                    "date": r.return_bill_date.isoformat() if r.return_bill_date else None,
                    "item_name": item_name_map.get(iid, ""),
                    "rate": round(cgst_pct + sgst_pct, 2),
                    "taxable_value": -taxable, "cgst_amount": -cgst_amt, "sgst_amount": -sgst_amt,
                    "total_tax": -(cgst_amt + sgst_amt), "gross_amount": -amount,
                })

        rate_summary = {}
        for l in lines:
            key = l["rate"]
            b = rate_summary.setdefault(key, {"rate": key, "taxable_value": 0.0, "cgst_amount": 0.0, "sgst_amount": 0.0, "total_tax": 0.0, "gross_amount": 0.0})
            b["taxable_value"] += l["taxable_value"]
            b["cgst_amount"] += l["cgst_amount"]
            b["sgst_amount"] += l["sgst_amount"]
            b["total_tax"] += l["total_tax"]
            b["gross_amount"] += l["gross_amount"]

        lines.sort(key=lambda x: x["date"] or "", reverse=True)
        summary = {
            "total_taxable_value": sum(l["taxable_value"] for l in lines),
            "total_tax": sum(l["total_tax"] for l in lines),
            "total_gross": sum(l["gross_amount"] for l in lines),
            "rate_wise": sorted(rate_summary.values(), key=lambda x: x["rate"]),
        }

        return Response({"success": True, "data": lines, "summary": summary, "is_approximate": True})
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
