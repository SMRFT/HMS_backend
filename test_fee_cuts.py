import os
import django
import traceback
from pymongo import MongoClient

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from hospital.models import InsuranceProvider

def to_float(val):
    if val is None:
        return 0.0
    try:
        return float(str(val))
    except (ValueError, TypeError):
        return 0.0

def _bulk_get_employee_names(emp_ids: set) -> dict:
    if not emp_ids:
        return {}
    clean_ids = [str(e).strip() for e in emp_ids if e and str(e).strip()]
    if not clean_ids:
        return {}
    try:
        mongo_host = os.getenv('GLOBAL_DB_HOST') or 'mongodb://localhost:27017/'
        global_db_name = os.getenv('GLOBAL_DB_NAME') or 'Global'
        client = MongoClient(mongo_host)
        global_db = client[global_db_name]
        cursor = global_db['backend_diagnostics_profile'].find(
            {"employeeId": {"$in": clean_ids}},
            {"employeeId": 1, "employeeName": 1, "_id": 0}
        )
        return {doc["employeeId"]: doc.get("employeeName", "") for doc in cursor if doc.get("employeeId")}
    except Exception as e:
        print(f"[ERROR] _bulk_get_employee_names failed: {e}")
        return {}

try:
    print("Testing PyMongo doctor fee cuts query with doctor name resolution...")
    mongo_host = os.getenv('GLOBAL_DB_HOST') or 'mongodb://localhost:27017/'
    client = MongoClient(mongo_host)
    db = client['HMS']

    query = {"is_admitted": True, "is_cancelled": {"$ne": True}}
    admissions = list(db['hospital_admission'].find(query).sort("admissionDateTime", -1))
    print("Admissions count:", len(admissions))

    providers = {p.company_code: p.company_name for p in InsuranceProvider.objects.all() if p.company_code}

    parsed_admissions = []
    all_doctor_ids = set()

    for adm in admissions:
        ip_number = adm.get('ipNumber', '')
        uhid = adm.get('uhid', '')
        patient = db['hospital_patient'].find_one({"uhid": uhid}) if uhid else None
        
        customer_type = adm.get('customer_type', '') or (patient.get('customer_type', '') if patient else '') or 'General'
        company_code = adm.get('company_code', '') or (patient.get('company_code', '') if patient else '') or ''
        company_name = providers.get(company_code, '') or adm.get('insurance_company', '') or (patient.get('insurance_company', '') if patient else '') or ''

        patient_name = ""
        if patient:
            patient_name = f"{patient.get('firstName', '')} {patient.get('lastName', '')}".strip()
        if not patient_name:
            patient_name = adm.get('patient_name', '') or 'N/A'

        bill = db['hospital_dischargebilling'].find_one(
            {"ip_number": ip_number, "is_active": {"$ne": False}},
            sort=[("discharge_id", -1)]
        )
        if not bill:
            bill = db['hospital_estimatebilling'].find_one(
                {"ip_number": ip_number, "is_active": {"$ne": False}},
                sort=[("id", -1)]
            )

        total_amount = to_float(bill.get('total_amount')) if bill else 0.0
        discount_amount = to_float(bill.get('discount_amount') or bill.get('total_disc')) if bill else 0.0
        net_amount = to_float(bill.get('net_amount')) if bill else 0.0

        raw_doctors = []
        if bill and isinstance(bill.get('items'), list):
            for item in bill['items']:
                docs_list = item.get('doctors', [])
                if isinstance(docs_list, list):
                    for doc in docs_list:
                        if isinstance(doc, dict):
                            fee = to_float(doc.get('doctor_fee') or doc.get('fee') or doc.get('amount') or 0.0)
                            if doc.get('surgeon_id'):
                                doc_id = str(doc['surgeon_id'])
                                all_doctor_ids.add(doc_id)
                                raw_doctors.append({"id": doc_id, "role": "Surgeon", "fee": fee})
                            if doc.get('anaesthetist_id'):
                                doc_id = str(doc['anaesthetist_id'])
                                all_doctor_ids.add(doc_id)
                                raw_doctors.append({"id": doc_id, "role": "Anaesthetist", "fee": fee})
                            if doc.get('additional_anaesthetists'):
                                doc_id = str(doc['additional_anaesthetists'])
                                all_doctor_ids.add(doc_id)
                                raw_doctors.append({"id": doc_id, "role": "Additional Anaesthetist", "fee": fee})
                            if doc.get('additional_doctors'):
                                doc_id = str(doc['additional_doctors'])
                                all_doctor_ids.add(doc_id)
                                raw_doctors.append({"id": doc_id, "role": "Additional Doctor", "fee": fee})
                            if doc.get('doctor_id'):
                                doc_id = str(doc['doctor_id'])
                                all_doctor_ids.add(doc_id)
                                raw_doctors.append({"id": doc_id, "role": "Doctor", "fee": fee})
                            if doc.get('employee_id'):
                                doc_id = str(doc['employee_id'])
                                all_doctor_ids.add(doc_id)
                                raw_doctors.append({"id": doc_id, "role": "Doctor", "fee": fee})

        parsed_admissions.append({
            "adm": adm,
            "ip_number": ip_number,
            "uhid": uhid,
            "patient_name": patient_name,
            "customer_type": customer_type,
            "company_code": company_code,
            "company_name": company_name,
            "total_amount": total_amount,
            "discount_amount": discount_amount,
            "net_amount": net_amount,
            "raw_doctors": raw_doctors
        })

    emp_name_map = _bulk_get_employee_names(all_doctor_ids)

    results = []
    for item in parsed_admissions:
        ip_number = item['ip_number']
        uhid = item['uhid']

        doctor_breakdown = []
        calculated_doctor_fee = 0.0
        for d in item['raw_doctors']:
            doc_id = d['id']
            fee_val = d['fee']
            doc_name = emp_name_map.get(doc_id) or f"Doctor #{doc_id}"
            doctor_breakdown.append({
                "doctor_id": doc_id,
                "doctor_name": doc_name,
                "role": d['role'],
                "doctor_fee": fee_val
            })
            calculated_doctor_fee += fee_val

        claim = db['hospital_doctorfeecuts'].find_one(
            {"ip_number": ip_number, "is_active": {"$ne": False}},
            sort=[("_id", -1)]
        )

        if claim:
            doctor_fee_requested = to_float(claim.get('doctor_fee_requested'))
            doctor_fee_approved = to_float(claim.get('doctor_fee_approved') or claim.get('approved_amount'))
            claim_status = claim.get('claim_status', 'Pending')
            approved_date = str(claim.get('approved_date')) if claim.get('approved_date') else None
        else:
            doctor_fee_requested = calculated_doctor_fee
            doctor_fee_approved = 0.0
            claim_status = 'Pending'
            approved_date = None

        results.append({
            "ipNumber": ip_number,
            "uhid": uhid,
            "patient_name": item['patient_name'],
            "customer_type": item['customer_type'],
            "company_code": item['company_code'],
            "company_name": item['company_name'],
            "total_amount": item['total_amount'],
            "discount_amount": item['discount_amount'],
            "net_amount": item['net_amount'],
            "doctor_breakdown": doctor_breakdown,
            "calculated_doctor_fee": calculated_doctor_fee,
            "doctor_fee_requested": doctor_fee_requested,
            "doctor_fee_approved": doctor_fee_approved,
            "claim_status": claim_status,
            "approved_date": approved_date,
        })

    print("SUCCESS! Results count:", len(results))
    if results:
        print("Sample result:", results[0])

    from hospital.Views.DoctorFeeCuts import get_doctor_fee_cuts_report
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()
    request = factory.get('/doctor-fee-cuts-report/?from_date=2026-07-01&to_date=2026-07-31', HTTP_AUTH_HOSPITAL_CODE='SH001', HTTP_AUTH_USER_ID='60002')
    request.user = type('User', (), {'is_authenticated': True, 'is_active': True})()
    response = get_doctor_fee_cuts_report.__wrapped__(request)
    print("REPORT SUCCESS:", response.data.get('success'))
    print("GRAND TOTALS:", response.data.get('data', {}).get('grand_totals'))
    print("AVAILABLE DOCTORS COUNT:", len(response.data.get('data', {}).get('available_doctors', [])))
    print("DOCTORWISE REPORTS COUNT:", len(response.data.get('data', {}).get('doctorwise_reports', [])))
except Exception as e:
    traceback.print_exc()
