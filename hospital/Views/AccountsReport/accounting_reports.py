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

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def get_shift_summary_report(request):
    """
    Returns shift summary for cashier wise reports.
    Moved from hospital.Views.cashcounter
    """
    try:
        data = request.data
        from_date = data.get("from_date")
        to_date = data.get("to_date")
        hospital_code = data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
        branch_code = data.get("auth-branch-code")
        
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
            
        report_data = []
        for s in shifts:
            report_data.append({
                "shiftno": s.shiftno,
                "CashierID": s.CashierID,
                "User": cashier_name_map.get(s.CashierID, s.CashierID),
                "CashCounter": s.CashCounter,
                "OpeningBalance": _to_float(s.OpeningBalance),
                "ClosingBalance": _to_float(s.ClosingBalance),
                "collected_Amount": _to_float(s.collected_Amount),
                "PettyCashBalance": _to_float(s.PettyCashBalance),
                "RemittedToBank": _to_float(s.RemittedToBank),
                "HandOverAmount": _to_float(s.HandOverAmount),
                "SalesReturnAmount": _to_float(s.SalesReturnAmount),
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
    """
    try:
        status_f = request.GET.get("status", "Billed")
        from_f   = request.GET.get("from_date")
        to_f     = request.GET.get("to_date")
        
        all_records = list(DischargeBilling.objects.all())
        filtered = []
        
        for obj in all_records:
            if not obj.is_active: continue
            if status_f and obj.status != status_f: continue
            
            bd_date = _parse_date(obj.bill_date)
            if from_f:
                f_date = _parse_date(from_f)
                if f_date and bd_date and bd_date < f_date: continue
            if to_f:
                t_date = _parse_date(to_f)
                if t_date and bd_date and bd_date > t_date: continue
            
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
                "payment_mode": "Cash", # Default or extract from items
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
    """
    try:
        from_f = request.GET.get("from_date")
        to_f   = request.GET.get("to_date")
        is_insurance = request.GET.get("insurance") == "true"
        
        admissions = Admission.objects.all()
        
        # Build patient map
        # We'll collect UHIDs from all admissions first
        uhids = list(set(a.uhid for a in admissions if getattr(a, 'is_admissionActive', True)))
        patients = Patient.objects.filter(uhid__in=uhids)
        patient_map = {p.uhid: p for p in patients}
        
        report_data = []
        for adm in admissions:
            if not getattr(adm, 'is_admissionActive', True): continue
            
            p = patient_map.get(adm.uhid)
            if not p: continue
            
            # Filter insurance if requested
            if is_insurance:
                has_insurance = (
                    p.company_code or 
                    getattr(adm, 'insuranceCompanyName', None) or 
                    getattr(p, 'customer_type', '').lower() == 'insurance'
                )
                if not has_insurance: continue
                
            payments = _parse_json(adm.advance_payments)
            for pay in payments:
                if not isinstance(pay, dict) or pay.get('status') == 'Edited': continue
                
                paid_dt = pay.get('paid_datetime')
                if not paid_dt: continue
                
                # Date filtering
                if from_f or to_f:
                    p_date = _parse_date(paid_dt)
                    if not p_date: continue
                    
                    if from_f:
                        f_date = _parse_date(from_f)
                        if f_date and p_date < f_date: continue
                    if to_f:
                        t_date = _parse_date(to_f)
                        if t_date and p_date > t_date: continue
                
                report_data.append({
                    "ipNumber": adm.ipNumber,
                    "uhid": adm.uhid,
                    "patient_name": f"{p.firstName} {p.lastName}".strip(),
                    "age": p.age,
                    "gender": p.gender,
                    "amount": _to_float(pay.get('amount')),
                    "paid_date": _format_dt(paid_dt),
                    "payment_mode": pay.get('payment_details', {}).get('method', 'Cash'),
                    "bill_no": pay.get('bill_no', ''),
                    "insurance_company": getattr(adm, 'insuranceCompanyName', p.company_code or 'N/A'),
                    "admission_date": _format_dt(adm.admissionDateTime),
                })
                
        report_data.sort(key=lambda x: x["paid_date"], reverse=True)
        return Response({"success": True, "data": report_data})
    except Exception as e:
        import traceback
        print("Advance Registration Error:", str(e))
        print(traceback.format_exc())
        return Response({"success": False, "message": str(e)}, status=500)
