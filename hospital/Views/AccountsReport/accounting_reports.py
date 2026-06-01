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
from ...models import Cashcountershiftdetails, DischargeBilling, Admission, Patient

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
    """
    try:
        status_f = request.GET.get("status", "Billed")
        from_f   = request.GET.get("from_date")
        to_f     = request.GET.get("to_date")
        
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
        
        client.close()
        
        # Go to other detailed collection
        all_records = list(DischargeBilling.objects.filter(bill_no__in=bill_numbers))
        filtered = []
        
        for obj in all_records:
            if not obj.is_active: continue
            if status_f and obj.status != status_f: continue
            
            # Build patient details
            patient_details = {}
            if obj.uhid:
                try:
                    p = Patient.objects.get(uhid=obj.uhid)
                    patient_details = {
                        "patient_name": f"{p.firstName} {p.lastName}".strip(),
                        "age": p.age,
                        "gender": p.gender,
                    }
                except: pass
                
            filtered.append({
                "id": obj.discharge_id,
                "bill_no": obj.bill_no,
                "estimate_number": obj.estimate_number,
                "uhid": obj.uhid,
                "ip_number": obj.ip_number,
                "bill_date": obj.bill_date.isoformat() if obj.bill_date else None,
                "total_amount": _to_float(obj.total_amount),
                "advance_amount": _to_float(obj.advance_amount),
                "net_amount": _to_float(obj.net_amount),
                "total_disc": _to_float(obj.total_disc),
                "status": obj.status,
                "patient_details": patient_details,
                "payment_mode": "Cash",
            })
            
        filtered.sort(key=lambda x: x["bill_date"] or "", reverse=True)
        return Response({"success": True, "data": filtered})
    except Exception as e:
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
        
        # Query admissions containing these advance payments
        admissions = list(db["hospital_admission"].find({"advance_payments.bill_no": {"$in": bill_numbers}}))
        client.close()
        
        # Build patient map
        uhids = list(set(a["uhid"] for a in admissions if a.get('is_admissionActive', True)))
        patients = Patient.objects.filter(uhid__in=uhids)
        patient_map = {p.uhid: p for p in patients}
        
        report_data = []
        for adm in admissions:
            if not adm.get('is_admissionActive', True): continue
            
            uhid = adm.get("uhid")
            p = patient_map.get(uhid)
            if not p: continue
            
            # Filter insurance if requested
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
                
                bill_no = pay.get('bill_no')
                if not bill_no or bill_no not in bill_numbers: continue
                
                paid_dt = pay.get('paid_datetime')
                report_data.append({
                    "ipNumber": adm.get("ipNumber"),
                    "uhid": uhid,
                    "patient_name": f"{p.firstName} {p.lastName}".strip(),
                    "age": p.age,
                    "gender": p.gender,
                    "amount": _to_float(pay.get('amount')),
                    "paid_date": _format_dt(paid_dt),
                    "payment_mode": pay.get('payment_details', {}).get('method', 'Cash'),
                    "bill_no": bill_no,
                    "insurance_company": adm.get('insuranceCompanyName') or p.company_code or 'N/A',
                    "admission_date": _format_dt(adm.get("admissionDateTime")),
                })
                
        report_data.sort(key=lambda x: x["paid_date"], reverse=True)
        return Response({"success": True, "data": report_data})
    except Exception as e:
        import traceback
        print("Advance Registration Error:", str(e))
        print(traceback.format_exc())
        return Response({"success": False, "message": str(e)}, status=500)
