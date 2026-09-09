import os
import re
from datetime import datetime
from decimal import Decimal
from bson import ObjectId, Decimal128
from pymongo import MongoClient
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from rest_framework import status
from ..models import Patient, Admission, Billing

def safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        if isinstance(val, Decimal128):
            return float(val.to_decimal())
        return float(str(val))
    except (ValueError, TypeError):
        return default

def serialize_data(val):
    if isinstance(val, dict):
        return {k: serialize_data(v) for k, v in val.items()}
    elif isinstance(val, (list, tuple)):
        return [serialize_data(i) for i in val]
    elif isinstance(val, (Decimal, Decimal128)):
        return float(val.to_decimal()) if hasattr(val, 'to_decimal') else float(val)
    elif isinstance(val, ObjectId):
        return str(val)
    elif isinstance(val, datetime):
        return val.isoformat()
import pytz
from django.utils import timezone

def get_daily_summary_data(client, from_date_str=None, to_date_str=None):
    tz = pytz.timezone('Asia/Kolkata')
    now = timezone.now().astimezone(tz)
    
    # Parse from_date
    if from_date_str:
        try:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d")
        except ValueError:
            from_date = now.date()
    else:
        from_date = now.date()

    # Parse to_date
    if to_date_str:
        try:
            to_date = datetime.strptime(to_date_str, "%Y-%m-%d")
        except ValueError:
            to_date = from_date
    else:
        to_date = from_date
        
    from_str = from_date.strftime("%Y-%m-%d")
    to_str   = to_date.strftime("%Y-%m-%d")
    
    # Date range in IST
    start_ist = datetime(from_date.year, from_date.month, from_date.day, 0, 0, 0)
    end_ist   = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59, 999999)
    
    # Date range in UTC
    start_utc = tz.localize(start_ist).astimezone(pytz.UTC)
    end_utc   = tz.localize(end_ist).astimezone(pytz.UTC)
    
    global_db = client["Global"]
    hms_db    = client["HMS"]
    
    patient_coll        = hms_db["hospital_patient"]
    doctor_profile_coll = global_db["backend_diagnostics_profile"]
    admission_coll      = hms_db["hospital_admission"]
    discharge_coll      = hms_db["hospital_dischargebilling"]
    
    # 1. Cache Doctors
    doctor_cache = {}
    for doc in doctor_profile_coll.find({}, {"employeeId": 1, "employeeName": 1, "firstName": 1, "lastName": 1, "department": 1}):
        emp_id = str(doc.get("employeeId", ""))
        name = doc.get("employeeName") or f"{doc.get('firstName', '')} {doc.get('lastName', '')}".strip()
        doctor_cache[emp_id] = {
            "name": name,
            "department": doc.get("department", "")
        }
        
    def resolve_doctor(doc_id):
        if not doc_id:
            return "—"
        doc_str = str(doc_id)
        if doc_str in doctor_cache:
            return doctor_cache[doc_str]["name"]
        return doc_str

    # 2. Registered Patients in date range
    reg_docs = list(patient_coll.find({
        "$or": [
            {"created_date": {"$gte": start_utc, "$lte": end_utc}},
            {"created_date": {"$gte": start_ist, "$lte": end_ist}},
            {"registration_date": {"$gte": from_str, "$lte": to_str}},
        ]
    }).sort("created_date", -1))
    
    registered_list = []
    seen_uhids = set()
    for p in reg_docs:
        uhid = p.get("uhid")
        if not uhid or uhid in seen_uhids:
            continue
        seen_uhids.add(uhid)
        
        full_name = f"{p.get('salutation', '') or ''} {p.get('firstName', '') or ''} {p.get('lastName', '') or ''}".strip() or p.get("name") or uhid
        c_date = p.get("created_date")
        c_date_iso = c_date.isoformat() if isinstance(c_date, datetime) else str(c_date) if c_date else None
        
        registered_list.append({
            "uhid": uhid,
            "name": full_name,
            "age": p.get("age"),
            "age_type": p.get("age_type") or "Y",
            "gender": p.get("gender") or "—",
            "mobilePhone": p.get("mobilePhone") or p.get("home_phone") or "—",
            "bloodGroup": p.get("blood_group") or p.get("bloodGroup") or "—",
            "doctorName": resolve_doctor(p.get("doctorName") or p.get("referredBy")),
            "customerType": p.get("customer_type") or p.get("customerType") or "General",
            "insuranceCompany": p.get("insurance_company") or p.get("insuranceCompany") or "—",
            "registration_date": p.get("registration_date") or from_str,
            "created_date": c_date_iso,
            "city": p.get("city") or "—",
            "area": p.get("area") or "",
        })

    # 3. Admissions in date range
    adm_docs = list(admission_coll.find({
        "is_cancelled": {"$ne": True},
        "$or": [
            {"admissionDateTime": {"$gte": start_utc, "$lte": end_utc}},
            {"admissionDateTime": {"$gte": start_ist, "$lte": end_ist}},
            {"admissionDateTime": {"$gte": from_str, "$lte": to_str + "T23:59:59"}},
        ]
    }).sort("admissionDateTime", -1))
    
    adm_uhids = [a.get("uhid") for a in adm_docs if a.get("uhid")]
    pt_map = {}
    if adm_uhids:
        for pt in patient_coll.find({"uhid": {"$in": adm_uhids}}):
            u = pt.get("uhid")
            pt_name = f"{pt.get('salutation', '') or ''} {pt.get('firstName', '') or ''} {pt.get('lastName', '') or ''}".strip()
            pt_map[u] = {
                "name": pt_name or u,
                "age": pt.get("age"),
                "age_type": pt.get("age_type") or "Y",
                "gender": pt.get("gender") or "—",
                "mobilePhone": pt.get("mobilePhone") or pt.get("home_phone") or "—",
                "bloodGroup": pt.get("blood_group") or pt.get("bloodGroup") or "—",
            }
            
    admissions_list = []
    seen_ips = set()
    for a in adm_docs:
        ip = a.get("ipNumber")
        if not ip or ip in seen_ips:
            continue
        seen_ips.add(ip)
        
        uhid = a.get("uhid")
        pt_info = pt_map.get(uhid, {})
        
        adm_dt = a.get("admissionDateTime")
        adm_dt_iso = adm_dt.isoformat() if isinstance(adm_dt, datetime) else str(adm_dt) if adm_dt else None
        
        room_list = a.get("room_details") or []
        room_info = room_list[-1] if isinstance(room_list, list) and room_list else {}
        room_no = room_info.get("roomNo") or room_info.get("roomNumber") or room_info.get("room_number") or "—"
        bed_no  = room_info.get("bedNo") or room_info.get("bedNumber") or room_info.get("bed_number") or "—"
        room_cat= room_info.get("roomCategory") or room_info.get("category") or "General"
        
        adv_list = a.get("advance_payments") or []
        adv_total = sum(safe_float(adv.get("amount") or adv.get("advance_amount")) for adv in adv_list if isinstance(adv, dict))
        
        admissions_list.append({
            "ipNumber": ip,
            "uhid": uhid,
            "name": pt_info.get("name") or a.get("patient_name") or uhid,
            "age": pt_info.get("age") or a.get("age"),
            "age_type": pt_info.get("age_type") or a.get("age_type") or "Y",
            "gender": pt_info.get("gender") or a.get("gender") or "—",
            "mobilePhone": pt_info.get("mobilePhone") or a.get("mobilePhone") or "—",
            "admissionDateTime": adm_dt_iso,
            "admittingDoctorName": resolve_doctor(a.get("admittingDoctor")),
            "consultingDoctorName": resolve_doctor(a.get("consultingDoctor")),
            "roomNo": room_no,
            "bedNo": bed_no,
            "roomCategory": room_cat,
            "customerType": a.get("customer_type") or "General",
            "insuranceCompany": a.get("insurance_company") or "—",
            "advance_paid": adv_total,
            "reasonForAdmission": a.get("reasonForAdmission") or "",
            "is_admitted": a.get("is_admitted", True),
            "is_discharged": a.get("is_discharged", False),
            "ward_status": a.get("ward_status") or "Admitted",
        })

    # 4. Discharges in date range
    dis_docs = list(discharge_coll.find({
        "is_cancelled": {"$ne": True},
        "$or": [
            {"bill_date": {"$gte": from_str, "$lte": to_str}},
            {"bill_date": {"$gte": start_utc, "$lte": end_utc}},
            {"bill_date": {"$gte": start_ist, "$lte": end_ist}},
            {"lastmodified_date": {"$gte": start_utc, "$lte": end_utc}},
            {"created_date": {"$gte": start_utc, "$lte": end_utc}},
        ]
    }).sort("discharge_id", -1))
    
    adm_dis_docs = list(admission_coll.find({
        "is_discharged": True,
        "is_cancelled": {"$ne": True},
        "$or": [
            {"lastmodified_date": {"$gte": start_utc, "$lte": end_utc}},
            {"lastmodified_date": {"$gte": start_ist, "$lte": end_ist}},
        ]
    }))
    
    dis_uhids = [d.get("uhid") for d in dis_docs if d.get("uhid")] + [d.get("uhid") for d in adm_dis_docs if d.get("uhid")]
    if dis_uhids:
        for pt in patient_coll.find({"uhid": {"$in": dis_uhids}}):
            u = pt.get("uhid")
            pt_name = f"{pt.get('salutation', '') or ''} {pt.get('firstName', '') or ''} {pt.get('lastName', '') or ''}".strip()
            pt_map[u] = {
                "name": pt_name or u,
                "age": pt.get("age"),
                "age_type": pt.get("age_type") or "Y",
                "gender": pt.get("gender") or "—",
                "mobilePhone": pt.get("mobilePhone") or pt.get("home_phone") or "—",
            }
            
    discharges_list = []
    seen_dis_ips = set()
    for d in dis_docs:
        ip = d.get("ip_number") or d.get("ipNumber")
        if not ip or ip in seen_dis_ips:
            continue
        seen_dis_ips.add(ip)
        
        uhid = d.get("uhid")
        pt_info = pt_map.get(uhid, {})
        
        b_date = d.get("bill_date") or d.get("lastmodified_date") or d.get("created_date")
        b_date_iso = b_date.isoformat() if isinstance(b_date, datetime) else str(b_date) if b_date else from_str
        
        discharges_list.append({
            "discharge_id": d.get("discharge_id"),
            "ipNumber": ip,
            "uhid": uhid,
            "name": pt_info.get("name") or uhid,
            "age": pt_info.get("age"),
            "gender": pt_info.get("gender") or "—",
            "mobilePhone": pt_info.get("mobilePhone") or "—",
            "bill_no": d.get("bill_no") or d.get("estimate_number") or f"DIS-{d.get('discharge_id')}",
            "bill_date": b_date_iso,
            "status": d.get("status") or "Billed",
            "total_amount": safe_float(d.get("total_amount")),
            "discount_amount": safe_float(d.get("discount_amount")),
            "advance_amount": safe_float(d.get("advance_amount")),
            "net_amount": safe_float(d.get("net_amount")),
            "discharged_by": d.get("created_by") or d.get("lastmodified_by") or "Staff",
        })
        
    for a in adm_dis_docs:
        ip = a.get("ipNumber")
        if not ip or ip in seen_dis_ips:
            continue
        seen_dis_ips.add(ip)
        uhid = a.get("uhid")
        pt_info = pt_map.get(uhid, {})
        
        discharges_list.append({
            "discharge_id": None,
            "ipNumber": ip,
            "uhid": uhid,
            "name": pt_info.get("name") or uhid,
            "age": pt_info.get("age"),
            "gender": pt_info.get("gender") or "—",
            "mobilePhone": pt_info.get("mobilePhone") or "—",
            "bill_no": "—",
            "bill_date": from_str,
            "status": "Discharged",
            "total_amount": 0,
            "discount_amount": 0,
            "advance_amount": 0,
            "net_amount": 0,
            "discharged_by": a.get("lastmodified_by") or resolve_doctor(a.get("admittingDoctor")) or "Staff",
        })

    # Recent previews (10 most recent of each for quick reference)
    recent_reg = []
    for p in patient_coll.find({}).sort("created_date", -1).limit(10):
        u = p.get("uhid")
        if not u: continue
        full_name = f"{p.get('salutation', '') or ''} {p.get('firstName', '') or ''} {p.get('lastName', '') or ''}".strip() or p.get("name") or u
        c_date = p.get("created_date")
        recent_reg.append({
            "uhid": u,
            "name": full_name,
            "age": p.get("age"),
            "gender": p.get("gender") or "—",
            "mobilePhone": p.get("mobilePhone") or p.get("home_phone") or "—",
            "registration_date": p.get("registration_date") or (c_date.strftime("%Y-%m-%d") if isinstance(c_date, datetime) else "—"),
            "doctorName": resolve_doctor(p.get("doctorName") or p.get("referredBy")),
        })

    recent_adm = []
    for a in admission_coll.find({"is_cancelled": {"$ne": True}}).sort("admissionDateTime", -1).limit(10):
        ip = a.get("ipNumber")
        if not ip: continue
        u = a.get("uhid")
        pt_info = pt_map.get(u, {})
        adm_dt = a.get("admissionDateTime")
        room_list = a.get("room_details") or []
        room_info = room_list[-1] if isinstance(room_list, list) and room_list else {}
        recent_adm.append({
            "ipNumber": ip,
            "uhid": u,
            "name": pt_info.get("name") or a.get("patient_name") or u,
            "admissionDateTime": adm_dt.isoformat() if isinstance(adm_dt, datetime) else str(adm_dt) if adm_dt else None,
            "admittingDoctorName": resolve_doctor(a.get("admittingDoctor")),
            "roomNo": room_info.get("roomNo") or room_info.get("roomNumber") or "—",
            "bedNo": room_info.get("bedNo") or room_info.get("bedNumber") or "—",
            "ward_status": a.get("ward_status") or "Admitted",
            "is_discharged": a.get("is_discharged", False),
        })

    return {
        "success": True,
        "is_summary": True,
        "from_date": from_str,
        "to_date": to_str,
        "date": from_str,
        "counts": {
            "registered": len(registered_list),
            "admissions": len(admissions_list),
            "discharges": len(discharges_list),
            "total_activity": len(registered_list) + len(admissions_list) + len(discharges_list),
        },
        "today_registered": registered_list,
        "today_admissions": admissions_list,
        "today_discharges": discharges_list,
        "recent_registered": recent_reg,
        "recent_admissions": recent_adm,
    }

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def patient_inquiry_view(request):
    """
    Comprehensive Patient Inquiry:
    If search parameter is provided:
      Fetches unified patient profile, OP registration visits, IP Admissions,
      Investigation / Lab / Radiology bills with detailed test lists,
      and Pharmacy bills with detailed medicine items.
    If no search parameter is provided (initial load / overview):
      Returns registered patients, admitted patients,
      and discharged patients summary and activity lists within from_date & to_date range.
    """
    try:
        search_query = request.GET.get('search', '').strip()
        uhid_param   = request.GET.get('uhid', '').strip()
        ip_param     = request.GET.get('ip_number', '').strip()
        mobile_param = request.GET.get('mobile', '').strip()
        from_date_param = request.GET.get('from_date', '').strip() or request.GET.get('date', '').strip()
        to_date_param   = request.GET.get('to_date', '').strip() or from_date_param

        raw_query = search_query or uhid_param or ip_param or mobile_param

        # Connect to MongoDB for Profiles & Collections
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))

        if not raw_query:
            summary_data = get_daily_summary_data(client, from_date_str=from_date_param, to_date_str=to_date_param)
            return Response(summary_data, status=status.HTTP_200_OK)

        global_db = client["Global"]
        hms_db    = client["HMS"]

        patient_coll        = hms_db["hospital_patient"]
        doctor_profile_coll = global_db["backend_diagnostics_profile"]
        invest_coll         = hms_db["hospital_investbilling"]
        pharmacy_coll       = hms_db["hospital_pharmacybilling"]
        pharm_item_coll     = hms_db["hospital_pharmacyitem"]
        admission_coll      = hms_db["hospital_admission"]

        patient = None
        matched_uhid = None

        # ── 1. Search Patient by UHID / IP / Mobile in Django ORM and Mongo ──
        patient = Patient.objects.filter(
            Q(uhid__iexact=raw_query) |
            Q(uhid__icontains=raw_query) |
            Q(mobilePhone__icontains=raw_query) |
            Q(firstName__icontains=raw_query) |
            Q(lastName__icontains=raw_query)
        ).first()

        # Check if raw_query is an IP Number in Admission ORM
        if not patient:
            adm_match = Admission.objects.filter(
                Q(ipNumber__iexact=raw_query) |
                Q(ipNumber__icontains=raw_query)
            ).first()
            if adm_match:
                matched_uhid = adm_match.uhid
                patient = Patient.objects.filter(
                    Q(uhid__iexact=matched_uhid) | Q(uhid__icontains=matched_uhid)
                ).first()

        # Check in MongoDB hospital_patient collection directly
        if not patient and not matched_uhid:
            mongo_pt = patient_coll.find_one({
                "$or": [
                    {"uhid": {"$regex": re.escape(raw_query), "$options": "i"}},
                    {"mobilePhone": {"$regex": re.escape(raw_query), "$options": "i"}},
                    {"firstName": {"$regex": re.escape(raw_query), "$options": "i"}},
                    {"lastName": {"$regex": re.escape(raw_query), "$options": "i"}},
                ]
            })
            if mongo_pt:
                matched_uhid = mongo_pt.get("uhid")
                patient = Patient.objects.filter(uhid=matched_uhid).first()

        # Check in MongoDB hospital_admission collection
        if not patient and not matched_uhid:
            mongo_adm = admission_coll.find_one({
                "$or": [
                    {"ipNumber": {"$regex": re.escape(raw_query), "$options": "i"}},
                    {"uhid": {"$regex": re.escape(raw_query), "$options": "i"}},
                ]
            })
            if mongo_adm:
                matched_uhid = mongo_adm.get("uhid")
                patient = Patient.objects.filter(uhid=matched_uhid).first()

        if not patient and not matched_uhid:
            return Response({
                "success": False,
                "message": f"No patient found for '{raw_query}'"
            }, status=status.HTTP_404_NOT_FOUND)

        uhid = patient.uhid if patient else matched_uhid
        uhid_suffix = uhid.split('/')[-1] if '/' in uhid else uhid

        # ── 2. Cache Doctor Profiles & Pharmacy Items ──
        doctor_cache = {}
        for doc in doctor_profile_coll.find({}, {"employeeId": 1, "employeeName": 1, "firstName": 1, "lastName": 1, "department": 1}):
            emp_id = str(doc.get("employeeId", ""))
            name = doc.get("employeeName") or f"{doc.get('firstName', '')} {doc.get('lastName', '')}".strip()
            doctor_cache[emp_id] = {
                "name": name,
                "department": doc.get("department", "")
            }

        pharm_item_cache = {}
        for item in pharm_item_coll.find({}, {"item_id": 1, "item_name": 1, "brand_name": 1}):
            i_id = item.get("item_id")
            if i_id is not None:
                pharm_item_cache[i_id] = item.get("item_name") or item.get("brand_name") or f"Item #{i_id}"
                pharm_item_cache[str(i_id)] = pharm_item_cache[i_id]

        # ── 3. Admissions (IP History) ──
        admissions_qs = Admission.objects.filter(
            Q(uhid__iexact=uhid) | Q(uhid__icontains=uhid_suffix)
        ).order_by('-admissionDateTime')
        
        admissions_list = []
        is_currently_admitted = False
        active_admission = None
        patient_ip_numbers = set()

        for adm in admissions_qs:
            if adm.ipNumber:
                patient_ip_numbers.add(adm.ipNumber)

            doc_id = str(adm.admittingDoctor or '')
            consult_id = str(adm.consultingDoctor or '')

            doc_info = doctor_cache.get(doc_id, {"name": adm.admittingDoctor, "department": ""})
            consult_info = doctor_cache.get(consult_id, {"name": adm.consultingDoctor, "department": ""})

            is_active = (adm.is_admitted and not adm.is_discharged and not adm.is_cancelled)
            if is_active and not active_admission:
                is_currently_admitted = True

            adm_dict = {
                "ipNumber": adm.ipNumber,
                "ipserial_number": adm.ipserial_number,
                "admissionDateTime": adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
                "admittingDoctorId": adm.admittingDoctor,
                "admittingDoctorName": doc_info["name"],
                "admittingDoctorDept": doc_info["department"],
                "consultingDoctorId": adm.consultingDoctor,
                "consultingDoctorName": consult_info["name"],
                "packageName": adm.packageName,
                "customer_type": adm.customer_type,
                "insurance_company": adm.insurance_company,
                "room_details": serialize_data(adm.room_details or []),
                "roomShitingDetails": serialize_data(adm.roomShitingDetails or []),
                "reasonForAdmission": adm.reasonForAdmission,
                "advance_payments": serialize_data(adm.advance_payments or []),
                "ward_status": adm.ward_status,
                "is_admitted": adm.is_admitted,
                "is_discharged": adm.is_discharged,
                "is_cancelled": adm.is_cancelled,
                "mlc_type": adm.mlc_type,
                "mlc_remarks": adm.mlc_remarks,
                "attender_name": getattr(adm, "attender_name", "") or "",
                "attender_relationship": getattr(adm, "attender_relationship", "") or "",
                "attender_phone": getattr(adm, "attender_phone", "") or "",
            }

            if is_active and not active_admission:
                active_admission = adm_dict

            admissions_list.append(adm_dict)

        # ── 4. OP Registration & Doctor Consultations ──
        reg_visits_list = []
        if patient:
            reg_billings = Billing.objects.filter(patient_id=patient.id).order_by('-billed_date')
            for b in reg_billings:
                d_id = str(b.doctor_id or '')
                d_info = doctor_cache.get(d_id, {"name": b.doctor_id, "department": ""})
                reg_visits_list.append({
                    "bill_number": b.bill_number,
                    "billed_date": b.billed_date.isoformat() if b.billed_date else None,
                    "doctor_id": b.doctor_id,
                    "doctor_name": d_info["name"],
                    "total_fees": safe_float(b.total_fees),
                    "payment_status": b.payment_status,
                    "payment_mode": getattr(b, 'payment_method', None) or getattr(b, 'payment_mode', 'Cash') or "Cash",
                })

        # ── 5. Investigation & Diagnostic Billing ──
        invest_or_clauses = [
            {"uhid": {"$regex": re.escape(uhid), "$options": "i"}},
            {"uhid": {"$regex": re.escape(uhid_suffix) + "$", "$options": "i"}}
        ]
        for ip in patient_ip_numbers:
            invest_or_clauses.append({"ipNumber": ip})

        invest_docs = list(invest_coll.find({"$or": invest_or_clauses}).sort("investBillDate", -1))
        invest_bills_list = []
        all_tests_master_list = []
        seen_invest_bills = set()

        for inv in invest_docs:
            b_no = inv.get("investBillNo")
            if b_no and b_no in seen_invest_bills:
                continue
            if b_no:
                seen_invest_bills.add(b_no)

            inv_doc_id = str(inv.get("doctor") or inv.get("consulting_doctor") or inv.get("referredBy") or '')
            inv_doc_info = doctor_cache.get(inv_doc_id, {"name": inv_doc_id, "department": ""})

            raw_items = inv.get("item") or inv.get("items") or inv.get("particulars") or inv.get("tests") or []
            tests = []
            for item in raw_items:
                test_name = (
                    item.get("itemName") or
                    item.get("test_name") or
                    item.get("particulars") or
                    item.get("item_name") or
                    item.get("service_name") or
                    "Diagnostic Test"
                )
                dept = item.get("department") or item.get("dept_name") or item.get("billTypeNo") or "Diagnostics"
                amt  = safe_float(item.get("price") or item.get("amount") or item.get("rate") or item.get("net_amount"))
                qty  = safe_float(item.get("quantity") or item.get("qty"), default=1)
                
                t_obj = {
                    "item_id": item.get("item_id") or item.get("test_id"),
                    "test_name": test_name,
                    "department": dept,
                    "quantity": qty,
                    "amount": amt,
                    "discount": safe_float(item.get("discount")),
                    "net_amount": amt,
                    "status": item.get("status", inv.get("paymentStatus", "Completed")),
                }
                tests.append(t_obj)

                all_tests_master_list.append({
                    "date": inv.get("investBillDate").isoformat() if isinstance(inv.get("investBillDate"), datetime) else inv.get("investBillDate"),
                    "bill_no": b_no,
                    "test_name": test_name,
                    "department": dept,
                    "doctor": inv_doc_info["name"],
                    "amount": amt,
                    "status": inv.get("paymentStatus", "Completed"),
                    "patientType": "IP" if inv.get("ipNumber") else "OP",
                })

            final_total = safe_float(inv.get("finalPrice") or inv.get("netAmount") or inv.get("totalAmount") or inv.get("total"))
            invest_bills_list.append({
                "investBillNo": b_no,
                "investBillDate": inv.get("investBillDate").isoformat() if isinstance(inv.get("investBillDate"), datetime) else inv.get("investBillDate"),
                "uhid": inv.get("uhid"),
                "ipNumber": inv.get("ipNumber"),
                "patientType": "IP" if inv.get("ipNumber") else "OP",
                "doctor_id": inv_doc_id,
                "doctor_name": inv_doc_info["name"],
                "bill_type": inv.get("bill_type"),
                "customer_type": inv.get("customer_type"),
                "insurance_company": inv.get("insurance_company"),
                "total_amount": safe_float(inv.get("total") or inv.get("totalAmount")),
                "discount_amount": safe_float(inv.get("discount") or inv.get("discountAmount")),
                "net_amount": final_total,
                "paid_amount": final_total if inv.get("paymentStatus") == "Paid" else safe_float(inv.get("paidAmount")),
                "billing_status": inv.get("paymentStatus") or inv.get("billing_status") or "Paid",
                "tests": tests,
            })

        # ── 6. Pharmacy Billing History ──
        pharm_or_clauses = [
            {"uhid": {"$regex": re.escape(uhid), "$options": "i"}},
            {"uhid": {"$regex": re.escape(uhid_suffix) + "$", "$options": "i"}}
        ]
        for ip in patient_ip_numbers:
            pharm_or_clauses.append({"inpatient_number": ip})

        pharm_docs = list(pharmacy_coll.find({"$or": pharm_or_clauses}).sort("created_date", -1))
        pharm_bills_list = []
        all_medicines_master_list = []
        seen_pharm_bills = set()

        for pb in pharm_docs:
            b_key = pb.get("bill_no") or pb.get("estimate_no") or str(pb.get("Bill_id"))
            if b_key and b_key in seen_pharm_bills:
                continue
            if b_key:
                seen_pharm_bills.add(b_key)

            doc_id = str(pb.get("doctor_id") or '')
            d_info = doctor_cache.get(doc_id, {"name": doc_id, "department": ""})
            created_d = pb.get("bill_date") or pb.get("ward_request_date") or pb.get("created_date")

            raw_meds = pb.get("medicine_particulars") or pb.get("medicines") or pb.get("items") or []
            medicines = []
            for med in raw_meds:
                item_id = med.get("item_id")
                med_name = (
                    med.get("item_name") or
                    med.get("itemName") or
                    med.get("particulars") or
                    pharm_item_cache.get(item_id) or
                    f"Medicine #{item_id or ''}".strip()
                )
                qty = safe_float(med.get("quantity") or med.get("qty"), default=1)
                u_price = safe_float(med.get("unit_price") or med.get("price") or med.get("rate") or med.get("mrp"))
                amt = safe_float(med.get("amount") or med.get("calculated_price") or med.get("total") or (qty * u_price))

                m_obj = {
                    "item_id": item_id,
                    "item_name": med_name,
                    "batch_number": med.get("batch_number") or "—",
                    "expiry_date": med.get("expiry_date"),
                    "dosage": med.get("dosage") or "—",
                    "days": med.get("noOfDays") or med.get("days") or "—",
                    "quantity": qty,
                    "unit_price": u_price,
                    "amount": amt,
                }
                medicines.append(m_obj)

                all_medicines_master_list.append({
                    "date": created_d.isoformat() if isinstance(created_d, datetime) else created_d,
                    "bill_no": b_key,
                    "medicine_name": med_name,
                    "dosage": med.get("dosage") or "—",
                    "quantity": qty,
                    "batch_number": med.get("batch_number") or "—",
                    "doctor": d_info["name"],
                    "amount": amt,
                    "status": pb.get("billing_status") or "Paid",
                    "patientType": "IP" if pb.get("inpatient_number") else "OP",
                })

            pharm_bills_list.append({
                "Bill_id": pb.get("Bill_id"),
                "bill_no": pb.get("bill_no"),
                "estimate_no": pb.get("estimate_no"),
                "bill_date": created_d.isoformat() if isinstance(created_d, datetime) else created_d,
                "uhid": pb.get("uhid"),
                "inpatient_number": pb.get("inpatient_number"),
                "patientType": "IP" if pb.get("inpatient_number") else "OP",
                "doctor_id": doc_id,
                "doctor_name": d_info["name"],
                "room_no": pb.get("room_no"),
                "total_amount": safe_float(pb.get("total_amount")),
                "discount_amount": safe_float(pb.get("overall_discount_amount")),
                "net_amount": safe_float(pb.get("net_amount") or pb.get("total_amount")),
                "billing_status": pb.get("billing_status") or "Paid",
                "billing_mode": pb.get("billing_mode") or "PHARMACY",
                "payment_mode": pb.get("payment_mode") or "Cash",
                "medicines": medicines,
            })

        # ── 7. Calculate Summary Stats ──
        total_invest_spend = sum(b.get("net_amount", 0) for b in invest_bills_list)
        total_pharm_spend  = sum(b.get("net_amount", 0) for b in pharm_bills_list)
        total_reg_spend    = sum(b.get("total_fees", 0) for b in reg_visits_list)

        total_advance_paid = 0
        for adm in admissions_list:
            for adv in adm.get("advance_payments", []):
                total_advance_paid += safe_float(adv.get("amount") or adv.get("advance_amount"))

        total_spend = total_invest_spend + total_pharm_spend + total_reg_spend + total_advance_paid

        # ── 8. Compile Patient Profile Object ──
        patient_profile = {}
        if patient:
            full_name = f"{getattr(patient, 'salutation', '') or ''} {getattr(patient, 'firstName', '') or ''} {getattr(patient, 'lastName', '') or ''}".strip()
            patient_profile = {
                "id": getattr(patient, 'id', None),
                "uhid": getattr(patient, 'uhid', uhid),
                "name": full_name or str(uhid),
                "firstName": getattr(patient, 'firstName', ''),
                "lastName": getattr(patient, 'lastName', ''),
                "salutation": getattr(patient, 'salutation', ''),
                "gender": getattr(patient, 'gender', '—'),
                "age": getattr(patient, 'age', None),
                "age_type": getattr(patient, 'age_type', 'Y'),
                "dob": patient.dob.isoformat() if getattr(patient, 'dob', None) else None,
                "bloodGroup": getattr(patient, 'blood_group', None) or getattr(patient, 'bloodGroup', None),
                "mobilePhone": getattr(patient, 'mobilePhone', None) or getattr(patient, 'home_phone', None),
                "address": getattr(patient, 'permanent_address', None) or getattr(patient, 'address', None),
                "area": getattr(patient, 'area', None),
                "city": getattr(patient, 'city', None),
                "state": getattr(patient, 'state', None),
                "pincode": getattr(patient, 'zipcode', None) or getattr(patient, 'pincode', None),
                "guardianName": getattr(patient, 'guardianName', None) or getattr(patient, 'spouse_name', None),
                "customerType": getattr(patient, 'customer_type', None) or getattr(patient, 'customerType', 'General') or "General",
                "insuranceCompany": getattr(patient, 'insurance_company', None) or getattr(patient, 'insuranceCompany', '—') or "—",
                "registeredDate": getattr(patient, 'registration_date', None) or (patient.created_date.isoformat() if getattr(patient, 'created_date', None) else None),
            }
        else:
            patient_profile = {
                "uhid": uhid,
                "name": raw_query or "Patient",
                "customerType": "General",
            }

        return Response({
            "success": True,
            "patient": patient_profile,
            "patient_type": "IP" if (is_currently_admitted or len(admissions_list) > 0) else "OP",
            "is_currently_admitted": is_currently_admitted,
            "active_admission": active_admission,
            "admissions": admissions_list,
            "registration_visits": reg_visits_list,
            "investigation_bills": invest_bills_list,
            "all_tests_list": all_tests_master_list,
            "pharmacy_bills": pharm_bills_list,
            "all_medicines_list": all_medicines_master_list,
            "summary_stats": {
                "total_admissions": len(admissions_list),
                "total_op_visits": len(reg_visits_list),
                "total_invest_bills": len(invest_bills_list),
                "total_tests_count": len(all_tests_master_list),
                "total_pharmacy_bills": len(pharm_bills_list),
                "total_medicines_count": len(all_medicines_master_list),
                "total_invest_amount": round(total_invest_spend, 2),
                "total_pharmacy_amount": round(total_pharm_spend, 2),
                "total_reg_amount": round(total_reg_spend, 2),
                "total_advance_amount": round(total_advance_paid, 2),
                "total_lifetime_spend": round(total_spend, 2),
            }
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
