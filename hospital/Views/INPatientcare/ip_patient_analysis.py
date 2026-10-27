from decimal import Decimal, InvalidOperation
import os
import re
import mimetypes
from bson.objectid import ObjectId
from pymongo import MongoClient
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework import status
from django.http import JsonResponse
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from pyauth.auth import HasRoleAndDataPermission
from datetime import datetime, date, timedelta
import traceback
import json
import ast


# ─────────────────────────────────────────────────────────────────────────────
# JSON & Data Serialization Helpers (Mirroring admission.py)
# ─────────────────────────────────────────────────────────────────────────────
def make_json_serializable(obj):
    if obj is None:
        return None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [make_json_serializable(v) for v in obj]
    if hasattr(obj, '__class__') and obj.__class__.__name__ == 'ObjectId':
        return str(obj)
    if hasattr(obj, '__class__') and obj.__class__.__name__ == 'Decimal':
        return float(obj)
    return obj


def parse_json_field(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            return json.loads(value)
        except Exception:
            try:
                return ast.literal_eval(value)
            except Exception:
                return []
    return value if isinstance(value, list) else []


def _safe_list(value):
    result = parse_json_field(value)
    clean = result if isinstance(result, list) else []
    return make_json_serializable(clean)


def _to_float(v):
    try:
        if v is None:
            return 0.0
        if isinstance(v, Decimal):
            return float(v)
        if hasattr(v, 'to_decimal'):
            return float(v.to_decimal())
        if isinstance(v, str):
            clean = v.replace(',', '').replace('₹', '').strip()
            return float(clean) if clean else 0.0
        return float(v)
    except Exception:
        return 0.0


def _parse_date(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        # ISO format YYYY-MM-DD
        try:
            return date.fromisoformat(val[:10])
        except Exception:
            pass
        # Standard formats
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y"):
            try:
                return datetime.strptime(val[:11].strip(), fmt).date()
            except Exception:
                continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Database connection helper (Identical to admission.py)
# ─────────────────────────────────────────────────────────────────────────────
def _get_hms_db():
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    hms_db = client[os.getenv("HMS_DB_NAME", "HMS")]
    return client, hms_db


# ─────────────────────────────────────────────────────────────────────────────
# Room & Doctor resolution helpers (Identical to admission.py)
# ─────────────────────────────────────────────────────────────────────────────
def _get_current_room_number(adm):
    """Resolves active room number using roomShitingDetails and room_details like admission.py"""
    shifts = _safe_list(adm.get("roomShitingDetails", []))
    for s in reversed(shifts):
        if isinstance(s, dict) and s.get("is_roomActive") in (True, "True", "true", 1, "1"):
            room_no = str(s.get("newRoomNo") or "").strip()
            if room_no:
                return room_no

    details = _safe_list(adm.get("room_details", []))
    for r in reversed(details):
        if isinstance(r, dict) and r.get("is_roomActive") in (True, "True", "true", 1, "1"):
            room_no = str(r.get("roomNo") or "").strip()
            if room_no:
                return room_no

    if details and isinstance(details[0], dict):
        room_no = str(details[0].get("roomNo") or "").strip()
        if room_no:
            return room_no

    return str(adm.get("roomNo") or "N/A").strip()


# ─────────────────────────────────────────────────────────────────────────────
# GET  /ip-patient-analysis/
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def ip_patient_analysis_view(request):
    """
    Dedicated IP Patient Analysis Report API.
    Builds on admission data structure identical to admission.py, providing:
    - Room Number, Admitting Date, Admitting Dr, Advance Amount, Return Amount,
      Total Days, Total Outstanding, Bill Amount, From Date, To Date
    - Dynamic date-wise daily breakdown columns (e.g. September_26_2026 ... October_26_2026)
    - KPI Metrics & Summaries
    """
    client = None
    try:
        # Standard Auth Code Extraction (Identical to admission.py)
        employee_id   = (request.data.get('auth-user-id')       or request.headers.get('auth-user-id')       or "system")
        hospital_code = (request.data.get("auth-hospital-code") or request.headers.get("auth-hospital-code") or "system")
        branch_code   = (request.data.get("auth-branch-code")   or request.headers.get("Branch-Code")        or "system")
        outlet_code   = request.data.get('auth-outlet-code')

        # 1. Parse Request Query Parameters
        from_date_str = (request.GET.get("from_date") or request.GET.get("startDate") or "").strip()
        to_date_str   = (request.GET.get("to_date")   or request.GET.get("endDate")   or "").strip()
        status_filter = (request.GET.get("status") or "all").strip().lower()
        doctor_filter = (request.GET.get("admitting_doctor") or "").strip().lower()
        search_filter = (request.GET.get("search") or request.GET.get("q") or "").strip().lower()
        ip_filter     = (request.GET.get("ip_number") or "").strip()
        uhid_filter   = (request.GET.get("uhid") or "").strip()
        floor_filter  = (request.GET.get("floor") or "all").strip().lower()
        block_filter  = (request.GET.get("block") or "all").strip().lower()

        # Parse Date Range
        today = timezone.now().date()
        from_date = _parse_date(from_date_str) if from_date_str else (today - timedelta(days=30))
        to_date   = _parse_date(to_date_str)   if to_date_str   else today

        if from_date > to_date:
            from_date, to_date = to_date, from_date

        # Performance safety cap
        if (to_date - from_date).days > 180:
            from_date = to_date - timedelta(days=180)

        dt_start = datetime.combine(from_date, datetime.min.time())
        dt_end   = datetime.combine(to_date, datetime.max.time())

        # 2. Build Daily Columns List (Format: Month_D_YYYY, e.g. September_26_2026, October_1_2026)
        daily_columns = []
        curr_dt = from_date
        while curr_dt <= to_date:
            month_name = curr_dt.strftime("%B")
            col_key = f"{month_name}_{curr_dt.day}_{curr_dt.year}"
            daily_columns.append({
                "key": col_key,
                "date_iso": curr_dt.isoformat(),
                "display": curr_dt.strftime("%d %b %Y"),
                "day_label": curr_dt.strftime("%d %b"),
                "date_obj": curr_dt
            })
            curr_dt += timedelta(days=1)

        # 3. Build MongoDB Admission Query (Identical pattern to admission.py)
        query = {
            "is_cancelled": {"$ne": True}
        }
        if hospital_code and hospital_code != "system":
            query["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            query["branch_code"] = branch_code
        if outlet_code and outlet_code != "system":
            query["outlet_code"] = outlet_code

        if ip_filter:
            if "/" in ip_filter:
                query["ipNumber"] = {"$regex": f"^{re.escape(ip_filter)}$", "$options": "i"}
            else:
                query["ipNumber"] = {"$regex": re.escape(ip_filter), "$options": "i"}

        if uhid_filter:
            query["uhid"] = {"$regex": f"^{re.escape(uhid_filter)}$", "$options": "i"}

        if status_filter == 'admitted':
            query["is_admitted"] = True
            query["is_discharged"] = False
        elif status_filter == 'discharged':
            query["is_discharged"] = True
            query["admissionDateTime"] = {"$lte": dt_end, "$gte": dt_start}
        else:
            # All admissions active or within the selected date window
            query["$or"] = [
                {"is_admitted": True, "is_discharged": False},
                {"admissionDateTime": {"$lte": dt_end, "$gte": dt_start}}
            ]

        if doctor_filter and doctor_filter != "all":
            query["admittingDoctor"] = {"$regex": re.escape(doctor_filter), "$options": "i"}

        # Connect MongoDB via _get_hms_db() (Same as admission.py)
        client, hms_db = _get_hms_db()

        # Fetch Admissions
        admissions = list(hms_db["hospital_admission"].find(query).sort("admissionDateTime", -1).limit(1000))

        # Doctor Map Resolution (Identical to admission.py lines 595-606 & Global db)
        doctor_map = {}
        try:
            doc_query = {}
            if hospital_code and hospital_code != "system":
                doc_query["hospital_code"] = hospital_code
            for d in hms_db["hospital_employee"].find(doc_query, {"employeeId": 1, "employeeName": 1}):
                e_id = str(d.get("employeeId") or "").strip()
                e_name = str(d.get("employeeName") or "").strip()
                if e_id and e_name:
                    doctor_map[e_id] = e_name
        except Exception:
            pass

        try:
            global_db = client['Global']
            for d in global_db['backend_diagnostics_profile'].find({}, {"employeeId": 1, "employeeName": 1}):
                e_id = str(d.get("employeeId") or "").strip()
                e_name = str(d.get("employeeName") or "").strip()
                if e_id and e_name and e_id not in doctor_map:
                    doctor_map[e_id] = e_name
        except Exception:
            pass

        # Pre-fetch Rooms
        room_query = {"is_active": True}
        if hospital_code and hospital_code != "system":
            room_query["hospital_code"] = hospital_code
        rooms_list = list(hms_db["hospital_room"].find(room_query))
        room_map = {str(r.get("room_number")).strip(): r for r in rooms_list if r.get("room_number")}

        # Pre-fetch Patients in batch (Identical to _enrich_admissions_batch in admission.py)
        uhid_set = list({str(a.get("uhid")).strip() for a in admissions if a.get("uhid")})
        pt_query = {"uhid": {"$in": uhid_set}}
        if hospital_code and hospital_code != "system":
            pt_query["hospital_code"] = hospital_code

        patients_list = list(hms_db["hospital_patient"].find(pt_query))
        patient_map = {}
        for p in patients_list:
            u_key = str(p.get("uhid") or "").strip()
            addr_parts = [
                p.get("permanent_address") or p.get("address"),
                p.get("doorNo"),
                p.get("street"),
                p.get("area"),
                p.get("city"),
                p.get("district")
            ]
            clean_addr = ", ".join([str(part).strip() for part in addr_parts if part and str(part).strip()])
            full_name = " ".join(filter(None, [
                p.get("salutation"),
                p.get("firstName"),
                p.get("middleName"),
                p.get("lastName")
            ])).strip() or "N/A"

            patient_map[u_key] = {
                "name": full_name,
                "age": p.get("age") or "N/A",
                "gender": p.get("gender") or "N/A",
                "mobile": p.get("mobilePhone") or "N/A",
                "address": clean_addr or "N/A"
            }

        # IP Numbers list for bulk lookups
        ip_numbers = [str(a.get("ipNumber") or "").strip() for a in admissions if a.get("ipNumber")]

        # Bulk fetch Refunds from hospital_ipadvance_refund
        refund_query = {
            "ip_number": {"$in": ip_numbers},
            "status": {"$ne": "Cancelled"}
        }
        if hospital_code and hospital_code != "system":
            refund_query["hospital_code"] = hospital_code

        refunds_list = list(hms_db["hospital_ipadvance_refund"].find(refund_query))
        refund_map = {}
        for ref in refunds_list:
            ip_k = str(ref.get("ip_number") or "").strip()
            refund_map[ip_k] = refund_map.get(ip_k, 0.0) + _to_float(ref.get("refund_amount", 0))

        # Bulk fetch Discharge Billings
        discharge_bills = list(hms_db["hospital_dischargebilling"].find({
            "ip_number": {"$in": ip_numbers},
            "is_cancelled": {"$ne": True}
        }))
        discharge_map = {}
        for d in discharge_bills:
            ip_k = str(d.get("ip_number") or "").strip()
            discharge_map[ip_k] = d

        # Bulk fetch Pharmacy IP Bills
        pharm_bills = list(hms_db["hospital_pharmacybilling"].find({
            "inpatient_number": {"$in": ip_numbers},
            "billing_status": "Paid"
        }))
        pharm_date_map = {}
        pharm_ip_total = {}
        for pb in pharm_bills:
            ip_k = str(pb.get("inpatient_number") or "").strip()
            amt = _to_float(pb.get("net_amount", 0))
            b_dt = _parse_date(pb.get("bill_date") or pb.get("created_date"))
            if b_dt:
                d_key = (ip_k, b_dt.isoformat())
                pharm_date_map[d_key] = pharm_date_map.get(d_key, 0.0) + amt
            pharm_ip_total[ip_k] = pharm_ip_total.get(ip_k, 0.0) + amt

        # Bulk fetch Investigation IP Bills
        inv_bills = list(hms_db["hospital_investbilling"].find({
            "inpatient_number": {"$in": ip_numbers},
            "status": {"$ne": "Cancelled"}
        }))
        inv_date_map = {}
        inv_ip_total = {}
        for ib in inv_bills:
            ip_k = str(ib.get("inpatient_number") or "").strip()
            amt = _to_float(ib.get("net_amount") or ib.get("total_amount") or 0)
            b_dt = _parse_date(ib.get("bill_date") or ib.get("created_date"))
            if b_dt:
                d_key = (ip_k, b_dt.isoformat())
                inv_date_map[d_key] = inv_date_map.get(d_key, 0.0) + amt
            inv_ip_total[ip_k] = inv_ip_total.get(ip_k, 0.0) + amt

        # 4. Process Admissions into Analysis Records
        records = []
        total_admitted_count = 0
        new_admissions_count = 0
        total_stay_days = 0

        # UHID occurrence counter for re-admission rate
        uhid_counts = {}
        for a in admissions:
            u = str(a.get("uhid") or "").strip()
            if u:
                uhid_counts[u] = uhid_counts.get(u, 0) + 1

        for adm in admissions:
            ip_num = str(adm.get("ipNumber") or "").strip()
            uhid_val = str(adm.get("uhid") or "").strip()
            patient_info = patient_map.get(uhid_val, {
                "name": "N/A", "age": "N/A", "gender": "N/A", "mobile": "N/A", "address": "N/A"
            })

            # Admission & Discharge Dates
            adm_dt_raw = adm.get("admissionDateTime")
            adm_date = _parse_date(adm_dt_raw) or today

            is_discharged = bool(adm.get("is_discharged", False))
            is_admitted   = bool(adm.get("is_admitted", False)) and not is_discharged
            dis_date      = _parse_date(adm.get("discharge_date") or adm.get("discharged_date"))

            # Active stay window: [adm_date, dis_date or today]
            stay_end = dis_date if (is_discharged and dis_date) else today
            if stay_end < from_date or adm_date > to_date:
                continue

            if is_admitted:
                total_admitted_count += 1
            if from_date <= adm_date <= to_date:
                new_admissions_count += 1

            # Resolve Current Active Room (Mirroring admission.py)
            room_no = _get_current_room_number(adm)
            room_obj = room_map.get(room_no)
            room_cat = room_obj.get("room_category") or "General" if room_obj else "General"
            block = room_obj.get("block") or "MAIN BLOCK" if room_obj else "MAIN BLOCK"
            floor = room_obj.get("floor") or "1st Floor" if room_obj else "1st Floor"

            # Apply floor and block filters
            if floor_filter != "all" and floor_filter not in str(floor).lower():
                continue
            if block_filter != "all" and block_filter not in str(block).lower():
                continue

            # Doctor Name Resolution (Mirroring admission.py)
            raw_doc = str(adm.get("admittingDoctor") or "").strip()
            doc_name = doctor_map.get(raw_doc) or str(adm.get("admittingDoctorName") or raw_doc)
            if doc_name and not doc_name.startswith("Dr.") and (raw_doc in doctor_map or not doc_name.isdigit()):
                doc_name = f"Dr. {doc_name}"
            if not doc_name or doc_name.strip() == "":
                doc_name = "N/A"

            if doctor_filter and doctor_filter != "all" and doctor_filter not in doc_name.lower() and doctor_filter not in raw_doc.lower():
                continue

            # Search text filter
            if search_filter:
                searchable_str = f"{ip_num} {uhid_val} {patient_info['name']} {room_no} {doc_name} {patient_info['address']}".lower()
                if search_filter not in searchable_str:
                    continue

            # Length of Stay (Total Days)
            total_days = max(1, (stay_end - adm_date).days) if stay_end >= adm_date else 1
            total_stay_days += total_days

            # Advance Amount (Extracted from advance_payments array identical to admission.py)
            adv_payments = _safe_list(adm.get("advance_payments"))
            total_advance = 0.0
            advance_refunds = 0.0
            for p in adv_payments:
                if isinstance(p, dict):
                    if p.get("status") in ("Cancelled", "Edited"):
                        continue
                    if p.get("is_advanceActive", True) in (False, "False", "false", 0, "0"):
                        continue
                    if p.get("is_refund"):
                        advance_refunds += _to_float(p.get("refund_amount") or p.get("advance_amount") or 0)
                    else:
                        total_advance += _to_float(p.get("advance_amount", 0))

            total_advance = round(total_advance, 2)

            # Return Amount (From hospital_ipadvance_refund + advance refund entries)
            total_return = round(refund_map.get(ip_num, 0.0) + advance_refunds, 2)

            # Bill Amount
            dis_bill = discharge_map.get(ip_num)
            total_bill = 0.0
            if dis_bill:
                total_bill = _to_float(dis_bill.get("net_amount") or dis_bill.get("total_amount") or 0)
            else:
                p_bill = pharm_ip_total.get(ip_num, 0.0)
                i_bill = inv_ip_total.get(ip_num, 0.0)
                room_rate = _to_float(room_obj.get("rent") or room_obj.get("room_rate") or 0) if room_obj else 0
                estimated_room_bill = room_rate * total_days
                total_bill = p_bill + i_bill + estimated_room_bill

            total_bill = round(total_bill, 2)

            # Total Outstanding: Bill Amount - Advance Amount + Return Amount
            total_outstanding = round(max(0.0, total_bill - total_advance + total_return), 2)

            # Daily Breakdown calculation across the selected date range
            daily_breakdown = {}
            for col in daily_columns:
                d_obj = col["date_obj"]
                col_k = col["key"]
                d_iso = col["date_iso"]
                day_amt = 0.0

                if adm_date <= d_obj <= stay_end:
                    day_amt += pharm_date_map.get((ip_num, d_iso), 0.0)
                    day_amt += inv_date_map.get((ip_num, d_iso), 0.0)
                    if dis_bill:
                        dis_b_dt = _parse_date(dis_bill.get("bill_date"))
                        if dis_b_dt == d_obj:
                            day_amt += _to_float(dis_bill.get("net_amount", 0))

                daily_breakdown[col_k] = round(day_amt, 2)

            # Record Payload
            rec = {
                "ip_number": ip_num,
                "uhid": uhid_val,
                "patient_name": patient_info["name"],
                "age": patient_info["age"],
                "gender": patient_info["gender"],
                "address": patient_info["address"],
                "room_number": room_no,
                "room_category": room_cat,
                "block": block,
                "floor": floor,
                "admitting_date": adm_date.strftime("%d/%m/%Y"),
                "admitting_date_iso": adm_date.isoformat(),
                "admitting_doctor": doc_name,
                "advance_amount": total_advance,
                "return_amount": total_return,
                "total_days": total_days,
                "total_outstanding": total_outstanding,
                "bill_amount": total_bill,
                "from_date": from_date.strftime("%d/%m/%Y"),
                "to_date": to_date.strftime("%d/%m/%Y"),
                "status": "Admitted" if is_admitted else "Discharged",
                "stay_end_date": stay_end.strftime("%d/%m/%Y"),
                "daily_breakdown": daily_breakdown
            }

            # Flatten dynamic daily columns directly on record
            for col_k, val in daily_breakdown.items():
                rec[col_k] = val

            records.append(rec)

        # Sort records by admitting date descending
        records.sort(key=lambda x: x["admitting_date_iso"], reverse=True)

        # 5. KPI Metrics & Column Summaries
        total_patients_count = len(records)
        avg_los = round(total_stay_days / total_patients_count, 1) if total_patients_count > 0 else 0.0

        readmitted_count = sum(1 for a in records if uhid_counts.get(a["uhid"], 0) > 1)
        readmission_rate = round((readmitted_count / total_patients_count) * 100, 2) if total_patients_count > 0 else 0.0

        total_beds_count = sum([len(r.get("beds") or [1]) for r in rooms_list]) or 569
        bed_occupancy_rate = round((total_admitted_count / max(1, total_beds_count)) * 100, 1)

        total_advance_sum     = round(sum(r["advance_amount"] for r in records), 2)
        total_return_sum      = round(sum(r["return_amount"] for r in records), 2)
        total_outstanding_sum = round(sum(r["total_outstanding"] for r in records), 2)
        total_bill_sum        = round(sum(r["bill_amount"] for r in records), 2)

        daily_column_totals = {}
        for col in daily_columns:
            k = col["key"]
            daily_column_totals[k] = round(sum(r.get(k, 0.0) for r in records), 2)

        summary_metrics = {
            "admitted_patients": total_admitted_count,
            "avg_length_of_stay": avg_los,
            "new_admissions": new_admissions_count,
            "readmission_rate": readmission_rate,
            "readmission_count": readmitted_count,
            "bed_occupancy_rate": bed_occupancy_rate,
            "occupied_beds": total_admitted_count,
            "total_beds": total_beds_count,
            "total_records": total_patients_count,
            "total_advance": total_advance_sum,
            "total_return": total_return_sum,
            "total_outstanding": total_outstanding_sum,
            "total_bill": total_bill_sum,
            "daily_totals": daily_column_totals
        }

        # Response payload matching standard HMS conventions
        return Response({
            "success": True,
            "from_date": from_date.strftime("%d/%m/%Y"),
            "to_date": to_date.strftime("%d/%m/%Y"),
            "from_date_iso": from_date.isoformat(),
            "to_date_iso": to_date.isoformat(),
            "daily_columns": [{
                "key": c["key"],
                "display": c["display"],
                "day_label": c["day_label"],
                "date_iso": c["date_iso"]
            } for c in daily_columns],
            "metrics": summary_metrics,
            "data": records,
            "count": len(records)
        }, status=status.HTTP_200_OK)

    except Exception as e:
        traceback.print_exc()
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()
