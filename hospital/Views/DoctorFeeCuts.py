import os
import datetime
import traceback
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
from ..models import Patient, InsuranceProvider, DoctorFeeCuts, CommunicationLog
from ..serializers import DoctorFeeCutsSerializer

def to_float(val):
    if val is None:
        return 0.0
    if isinstance(val, dict):
        if '$numberDecimal' in val:
            val = val['$numberDecimal']
        elif 'amount' in val:
            val = val['amount']
    try:
        return float(str(val))
    except (ValueError, TypeError):
        return 0.0

def get_db():
    mongo_host = os.getenv('GLOBAL_DB_HOST') or 'mongodb://localhost:27017/'
    client = MongoClient(mongo_host)
    return client['HMS']


def _bulk_get_employee_names(emp_ids: set) -> dict:
    """
    Single pymongo query to global DB to fetch employee names by employeeId.
    """
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


def _bulk_get_employee_profiles(emp_ids: set) -> dict:
    """
    Fetch employee names and email addresses from global DB by employeeId.
    Returns dict: { employeeId: { "name": employeeName, "email": email } }
    """
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
            {"employeeId": 1, "employeeName": 1, "email": 1, "officialEmail": 1, "personalEmail": 1, "_id": 0}
        )
        res = {}
        for doc in cursor:
            e_id = doc.get("employeeId")
            if e_id:
                name = doc.get("employeeName", "")
                email = doc.get("email") or doc.get("officialEmail") or doc.get("personalEmail") or ""
                res[e_id] = {"name": name, "email": email}
        return res
    except Exception as e:
        print(f"[ERROR] _bulk_get_employee_profiles failed: {e}")
        return {}


def _extract_raw_doctors_from_billing(bill):
    """
    Extract raw doctors list from billing document items.
    Handles surgeon_id, anaesthetist_id, additional_anaesthetists, additional_doctors, doctor_id, employee_id.
    """
    raw_doctors = []
    if not bill or not isinstance(bill.get('items'), list):
        return raw_doctors

    for item in bill['items']:
        docs_list = item.get('doctors', [])
        if isinstance(docs_list, list):
            for doc in docs_list:
                if isinstance(doc, dict):
                    fee = to_float(doc.get('doctor_fee') or doc.get('fee') or doc.get('amount') or 0.0)
                    if doc.get('surgeon_id'):
                        raw_doctors.append({"id": str(doc['surgeon_id']).strip(), "role": "Surgeon", "fee": fee})
                    if doc.get('anaesthetist_id'):
                        raw_doctors.append({"id": str(doc['anaesthetist_id']).strip(), "role": "Anaesthetist", "fee": fee})
                    if doc.get('additional_anaesthetists'):
                        raw_doctors.append({"id": str(doc['additional_anaesthetists']).strip(), "role": "Additional Anaesthetist", "fee": fee})
                    if doc.get('additional_doctors'):
                        raw_doctors.append({"id": str(doc['additional_doctors']).strip(), "role": "Additional Doctor", "fee": fee})
                    if doc.get('doctor_id'):
                        raw_doctors.append({"id": str(doc['doctor_id']).strip(), "role": "Doctor", "fee": fee})
                    if doc.get('employee_id'):
                        raw_doctors.append({"id": str(doc['employee_id']).strip(), "role": "Doctor", "fee": fee})
    return raw_doctors


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_patient_admission_details(request):
    """
    Fetch patient and admission details by UHID or IP Number.
    """
    uhid = request.GET.get('uhid')
    ip_number = request.GET.get('ip_number')
    
    try:
        db = get_db()
        admission = None
        if uhid:
            admission = db['hospital_admission'].find_one({"uhid": uhid})
        elif ip_number:
            admission = db['hospital_admission'].find_one({"ipNumber": ip_number})

        if not admission:
            return Response({"success": False, "error": f"Admission not found for {uhid or ip_number}"}, status=404)

        if '_id' in admission:
            admission['_id'] = str(admission['_id'])

        return Response({"success": True, "data": admission})

    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_admitted_doctor_fee_patients(request):
    """
    Fetch all admitted patients (is_admitted=True) from Admission model,
    and retrieve total fee (total_amount), discount_amount, net_amount, medicines_amount, implant_amount from DischargeBilling
    (fallback to EstimateBilling if DischargeBilling not found),
    along with doctor breakdown and Doctor Fee Cut details.
    """
    hospital_code = request.headers.get("auth-hospital-code") or "system"
    company_filter = request.GET.get('company')
    status_filter = (request.GET.get('status') or 'ALL').strip()
    search_query = (request.GET.get('search') or '').strip().lower()
    from_date_str = request.GET.get('from_date') or request.GET.get('fromDate')
    to_date_str = request.GET.get('to_date') or request.GET.get('toDate')

    from_dt = None
    to_dt = None
    if from_date_str:
        try:
            from_dt = datetime.datetime.strptime(from_date_str[:10], "%Y-%m-%d")
        except Exception:
            pass
    if to_date_str:
        try:
            to_dt = datetime.datetime.strptime(to_date_str[:10], "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except Exception:
            pass

    try:
        db = get_db()
        
        # Get all active admitted patients (is_admitted=True, is_cancelled != True)
        query = {"is_admitted": True, "is_cancelled": {"$ne": True}}
        admissions = list(db['hospital_admission'].find(query).sort("admissionDateTime", -1))
        
        # Cache Insurance Providers for fast company_name lookup
        providers = {p.company_code: p.company_name for p in InsuranceProvider.objects.all() if p.company_code}

        # Step 1: Pre-process admissions and fetch billing records + collect all doctor IDs
        parsed_admissions = []
        all_doctor_ids = set()

        for adm in admissions:
            ip_number = adm.get('ipNumber', '')
            uhid = adm.get('uhid', '')
            
            patient = db['hospital_patient'].find_one({"uhid": uhid}) if uhid else None
            
            customer_type = adm.get('customer_type', '') or (patient.get('customer_type', '') if patient else '') or 'General'
            company_code = adm.get('company_code', '') or (patient.get('company_code', '') if patient else '') or ''
            company_name = providers.get(company_code, '') or adm.get('insurance_company', '') or (patient.get('insurance_company', '') if patient else '') or ''

            # Apply Insurance Company Filter
            if company_filter and company_filter != 'ALL':
                if company_name.lower() != company_filter.lower() and company_code.lower() != company_filter.lower():
                    continue

            # Construct patient name
            patient_name = ""
            if patient:
                patient_name = f"{patient.get('firstName', '')} {patient.get('lastName', '')}".strip()
            if not patient_name:
                patient_name = adm.get('patient_name', '') or 'N/A'

            # Apply search query (IP Number, UHID, Patient Name, Customer Type, Company Name)
            if search_query:
                q = search_query
                match = (
                    q in (ip_number or '').lower() or 
                    q in (uhid or '').lower() or 
                    q in patient_name.lower() or
                    q in customer_type.lower() or
                    q in company_name.lower()
                )
                if not match:
                    continue

            # Fetch Billing summary strictly from DischargeBilling
            bill = db['hospital_dischargebilling'].find_one(
                {
                    "$or": [{"ip_number": ip_number}, {"ipNumber": ip_number}],
                    "is_active": {"$ne": False},
                    "is_cancelled": {"$ne": True}
                },
                sort=[("discharge_id", -1), ("_id", -1)]
            )
            # If admission ipNumber is not available in Discharge Billing, skip it
            if not bill:
                continue

            total_amount = to_float(bill.get('total_amount'))
            discount_amount = to_float(bill.get('discount_amount') or bill.get('total_disc'))
            net_amount = to_float(bill.get('net_amount'))
            medicines_amount = to_float(bill.get('medicines_amount'))
            implant_amount = to_float(bill.get('implant_amount'))

            # Extract Doctors from Billing Items
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

            bill_date = bill.get('bill_date') or bill.get('created_date')

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
                "medicines_amount": medicines_amount,
                "implant_amount": implant_amount,
                "bill_date": bill_date,
                "raw_doctors": raw_doctors
            })

        # Step 2: Resolve doctor employee names in bulk
        emp_name_map = _bulk_get_employee_names(all_doctor_ids)

        # Step 3: Build final payload
        results = []
        for item in parsed_admissions:
            ip_number = item['ip_number']
            uhid = item['uhid']
            adm = item['adm']

            # Existing DoctorFeeCuts record for this IP Number
            claim = db['hospital_doctorfeecuts'].find_one(
                {"ip_number": ip_number, "is_active": {"$ne": False}},
                sort=[("_id", -1)]
            )

            status = (claim.get('status')) if claim else 'Pending'
            approved_by = claim.get('approved_by') if claim else None
            approved_date_raw = claim.get('approved_date') if claim else None
            if isinstance(approved_date_raw, (datetime.datetime, datetime.date)):
                approved_date = approved_date_raw.isoformat()
            elif approved_date_raw:
                approved_date = str(approved_date_raw)
            else:
                approved_date = None

            # Date check
            record_date_raw = claim.get('date') if claim else None
            if not record_date_raw:
                record_date_raw = item.get('bill_date') or adm.get('admissionDateTime') or adm.get('created_at')

            record_dt = None
            if isinstance(record_date_raw, (datetime.datetime, datetime.date)):
                if isinstance(record_date_raw, datetime.date) and not isinstance(record_date_raw, datetime.datetime):
                    record_dt = datetime.datetime.combine(record_date_raw, datetime.time.min)
                else:
                    record_dt = record_date_raw
            elif isinstance(record_date_raw, dict) and '$date' in record_date_raw:
                try:
                    record_dt = datetime.datetime.fromisoformat(str(record_date_raw['$date']).replace("Z", "+00:00"))
                except Exception:
                    pass
            elif record_date_raw:
                try:
                    record_dt = datetime.datetime.fromisoformat(str(record_date_raw).replace("Z", "+00:00"))
                except Exception:
                    try:
                        record_dt = datetime.datetime.strptime(str(record_date_raw)[:10], "%Y-%m-%d")
                    except Exception:
                        pass

            if record_dt and timezone.is_aware(record_dt):
                record_dt = timezone.make_naive(record_dt)

            if from_dt and record_dt:
                if record_dt < from_dt:
                    continue
            if to_dt and record_dt:
                if record_dt > to_dt:
                    continue

            stored_bd = claim.get('doctor_breakdown', []) if claim else []
            stored_map = {}
            if isinstance(stored_bd, list):
                for s in stored_bd:
                    key = (str(s.get('doctor_id', '')), str(s.get('role', '')))
                    stored_map[key] = s

            doctor_breakdown = []
            calculated_doctor_fee = 0.0
            sum_requested = 0.0
            sum_approved = 0.0

            for d in item['raw_doctors']:
                doc_id = d['id']
                role = d['role']
                bill_fee = d['fee']
                doc_name = emp_name_map.get(doc_id) or f"Doctor #{doc_id}"

                stored_item = stored_map.get((doc_id, role)) or stored_map.get((doc_id, ''))
                if stored_item and stored_item.get('requested_amount') is not None and stored_item.get('requested_amount') != "":
                    req_fee = to_float(stored_item.get('requested_amount'))
                else:
                    req_fee = ""

                if stored_item and stored_item.get('approved_amount') is not None and stored_item.get('approved_amount') != "":
                    app_fee = to_float(stored_item.get('approved_amount'))
                else:
                    app_fee = ""

                calculated_doctor_fee += bill_fee
                if req_fee != "":
                    sum_requested += to_float(req_fee)
                if app_fee != "":
                    sum_approved += to_float(app_fee)

                doctor_breakdown.append({
                    "doctor_id": doc_id,
                    "doctor_name": doc_name,
                    "role": role,
                    "doctor_fee": bill_fee,
                    "requested_amount": req_fee,
                    "approved_amount": app_fee
                })

            # Extract discharge doctor fees
            discharge_doctor_fees = []
            for d in item['raw_doctors']:
                doc_id = d['id']
                fee_val = d['fee']
                doc_name = emp_name_map.get(doc_id) or f"Doctor #{doc_id}"
                discharge_doctor_fees.append({
                    "doctor_id": doc_id,
                    "doctor_name": doc_name,
                    "role": d['role'],
                    "doctor_fee": fee_val
                })

            # Apply status filter (ALL, Pending, Requested, Approved)
            if status_filter and status_filter.upper() != 'ALL':
                if status.lower() != status_filter.lower():
                    continue

            results.append({
                "ipNumber": ip_number,
                "uhid": uhid,
                "patient_name": item['patient_name'],
                "admission_date": adm.get('admissionDateTime'),
                "bill_date": item.get('bill_date'),
                "admitting_doctor": adm.get('admittingDoctor', ''),
                "customer_type": item['customer_type'],
                "company_code": item['company_code'],
                "company_name": item['company_name'],
                "total_amount": item['total_amount'],
                "discount_amount": item['discount_amount'],
                "net_amount": item['net_amount'],
                "medicines_amount": item['medicines_amount'],
                "implant_amount": item['implant_amount'],
                "discharge_doctor_fees": discharge_doctor_fees,
                "doctor_breakdown": doctor_breakdown,
                "calculated_doctor_fee": calculated_doctor_fee,
                "doctor_fee_requested": sum_requested,
                "doctor_fee_approved": sum_approved,
                "status": status,
                "approved_by": approved_by,
                "approved_date": approved_date,
            })

        return Response({"success": True, "data": results})

    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def save_doctor_fee_claim(request):
    
    data = request.data
    hospital_code = data.get("auth-hospital-code") or "system"
    branch_code = data.get("auth-branch-code") or "system"
    employee_id = data.get("auth-user-id") or "system"

    data = request.data
    ip_number = data.get('ipNumber') or data.get('ip_number')
    if not ip_number:
        return Response({"success": False, "error": "ipNumber is required"}, status=400)

    try:
        db = get_db()

        # Retrieve DischargeBilling date directly from hospital_dischargebilling
        billing_doc = db['hospital_dischargebilling'].find_one({"ip_number": ip_number, "is_cancelled": {"$ne": True}}, sort=[("discharge_id", -1)])

        bill_date_raw = billing_doc.get('bill_date') or billing_doc.get('created_date') if billing_doc else None
        bill_date = None
        if isinstance(bill_date_raw, (datetime.datetime, datetime.date)):
            bill_date = bill_date_raw
        elif isinstance(bill_date_raw, dict) and '$date' in bill_date_raw:
            try:
                bill_date = datetime.datetime.fromisoformat(str(bill_date_raw['$date']).replace("Z", "+00:00"))
            except Exception:
                bill_date = timezone.now()
        elif bill_date_raw:
            try:
                bill_date = datetime.datetime.fromisoformat(str(bill_date_raw).replace("Z", "+00:00"))
            except Exception:
                bill_date = timezone.now()
        else:
            bill_date = timezone.now()

        doctor_breakdown_in = data.get('doctor_breakdown') or []
        cleaned_breakdown = []
        sum_req = 0.0
        sum_app = 0.0

        if isinstance(doctor_breakdown_in, list) and len(doctor_breakdown_in) > 0:
            for d in doctor_breakdown_in:
                req_v = to_float(d.get('requested_amount', d.get('doctor_fee', 0.0)))
                app_v = to_float(d.get('approved_amount', 0.0))
                sum_req += req_v
                sum_app += app_v
                # Store ONLY doctor_id, role, requested_amount, approved_amount
                cleaned_breakdown.append({
                    "doctor_id": str(d.get('doctor_id', '')),
                    "role": str(d.get('role', '')),
                    "requested_amount": req_v,
                    "approved_amount": app_v
                })
            req_amt = sum_req
            app_amt = sum_app
        else:
            req_amt = to_float(data.get('doctor_fee_requested', 0.0))
            app_amt = to_float(data.get('doctor_fee_approved', 0.0))

        action = data.get('action', '')
        status_in = data.get('status')

        if action == 'save_requested' or status_in == 'Requested':
            new_status = 'Requested'
        elif action == 'approve' or status_in == 'Approved':
            new_status = 'Approved'
        else:
            new_status = status_in or 'Pending'

        if new_status == 'Approved':
            invalid_approved = False
            if isinstance(doctor_breakdown_in, list) and len(doctor_breakdown_in) > 0:
                for d in doctor_breakdown_in:
                    app_val = to_float(d.get('approved_amount'))
                    raw_v = d.get('approved_amount')
                    if raw_v is None or raw_v == "" or app_val <= 0:
                        invalid_approved = True
                        break
            else:
                app_val = to_float(data.get('doctor_fee_approved'))
                raw_v = data.get('doctor_fee_approved')
                if raw_v is None or raw_v == "" or app_val <= 0:
                    invalid_approved = True

            if invalid_approved:
                return Response({
                    "success": False,
                    "error": "Approved amount must be greater than 0 for each doctor before approving."
                }, status=400)

        update_data = {
            "ip_number": ip_number,
            "uhid": data.get('uhid', ''),
            "doctor_breakdown": cleaned_breakdown,
            "status": new_status,
            "date": bill_date,
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "lastmodified_by": employee_id,
            "lastmodified_date": timezone.now(),
            "is_active": True
        }
        if new_status == 'Approved':
            update_data['approved_by'] = employee_id
            update_data['approved_date'] = timezone.now()

        set_on_insert = {
            "created_by": employee_id,
            "created_date": timezone.now()
        }

        db['hospital_doctorfeecuts'].update_one(
            {"ip_number": ip_number},
            {"$set": update_data, "$setOnInsert": set_on_insert},
            upsert=True
        )

        try:
            claim = DoctorFeeCuts.objects.filter(ip_number=ip_number, is_active=True).first()
            if not claim:
                claim = DoctorFeeCuts(
                    ip_number=ip_number,
                    uhid=data.get('uhid', ''),
                    hospital_code=hospital_code,
                    branch_code=branch_code,
                    created_by=employee_id,
                    created_date=timezone.now()
                )
            claim.date = bill_date
            claim.hospital_code = hospital_code
            claim.branch_code = branch_code
            claim.status = new_status
            if new_status == 'Approved':
                claim.approved_by = employee_id
                claim.approved_date = timezone.now()
            claim.lastmodified_by = employee_id
            claim.lastmodified_date = timezone.now()
            claim.save()
        except Exception as e:
            print(f"[NOTE] ORM Sync: {e}")

        return Response({
            "success": True, 
            "message": f"Doctor fee cut {'approved' if new_status == 'Approved' else 'saved'} successfully",
            "data": {
                "ipNumber": ip_number,
                "date": bill_date.isoformat() if isinstance(bill_date, (datetime.datetime, datetime.date)) else str(bill_date),
                "doctor_fee_requested": req_amt,
                "doctor_fee_approved": app_amt,
                "status": new_status,
                "approved_by": employee_id if new_status == 'Approved' else None,
                "doctor_breakdown": cleaned_breakdown
            }
        })
    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)



@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def doctor_fee_cuts_view(request, claim_id=None):
    """
    CRUD view for DoctorFeeCuts claims.
    """
    hospital_code = request.headers.get("auth-hospital-code") or "system"
    branch_code = request.headers.get("Branch-Code") or "system"
    employee_id = request.headers.get("auth-user-id") or "system"

    if request.method == 'GET':
        try:
            if claim_id:
                claim = DoctorFeeCuts.objects.filter(claim_id=claim_id, hospital_code=hospital_code).first()
                if not claim:
                    return Response({"success": False, "error": "Record not found"}, status=404)
                serializer = DoctorFeeCutsSerializer(claim)
                return Response({"success": True, "data": serializer.data})
            
            from_date = request.GET.get('from_date')
            to_date = request.GET.get('to_date')
            company = request.GET.get('company')
            show_deleted = request.GET.get('show_deleted') == 'true'

            query = DoctorFeeCuts.objects.filter(hospital_code=hospital_code)
            
            if not show_deleted:
                query = query.filter(is_active=True)
            
            if from_date:
                query = query.filter(claim_date__gte=from_date)
            if to_date:
                query = query.filter(claim_date__lte=to_date)
            if company and company != 'ALL':
                query = query.filter(insurance_company=company)

            claims = query.order_by('-claim_date')
            serializer = DoctorFeeCutsSerializer(claims, many=True)
            return Response({"success": True, "data": serializer.data})

        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'POST':
        try:
            data = request.data.copy()
            data['hospital_code'] = hospital_code
            data['branch_code'] = branch_code
            data['created_by'] = employee_id
            
            serializer = DoctorFeeCutsSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response({"success": True, "message": "Record created successfully", "data": serializer.data}, status=201)
            return Response({"success": False, "error": serializer.errors}, status=400)
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'PATCH':
        try:
            if not claim_id:
                return Response({"success": False, "error": "Claim ID required"}, status=400)
            
            claim = DoctorFeeCuts.objects.filter(claim_id=claim_id, hospital_code=hospital_code).first()
            if not claim:
                return Response({"success": False, "error": "Record not found"}, status=404)
            
            data = request.data.copy()
            data['lastmodified_by'] = employee_id
            
            serializer = DoctorFeeCutsSerializer(claim, data=data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response({"success": True, "message": "Record updated successfully", "data": serializer.data})
            return Response({"success": False, "error": serializer.errors}, status=400)
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'DELETE':
        try:
            if not claim_id:
                return Response({"success": False, "error": "Claim ID required"}, status=400)
            
            claim = DoctorFeeCuts.objects.filter(claim_id=claim_id, hospital_code=hospital_code).first()
            if not claim:
                return Response({"success": False, "error": "Record not found"}, status=404)
            
            claim.is_active = False
            claim.lastmodified_by = employee_id
            claim.save()
            
            return Response({"success": True, "message": "Record deleted successfully"})
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_doctor_fee_cuts_report(request):
    """
    Doctor Fee Cuts Report API endpoint.
    Filters by:
    - from_date (YYYY-MM-DD)
    - to_date (YYYY-MM-DD)
    - doctor_id (optional, default 'ALL')
    - status (optional, default 'ALL')

    Returns:
    - available_doctors: list of { doctor_id, doctor_name }
    - doctorwise_reports: list of doctor objects grouped doctorwise with patient records & total amounts.
    - grand_totals: summary of total_billed, total_requested, total_approved, total_patients.
    """
    from_date_str = request.GET.get('from_date')
    to_date_str = request.GET.get('to_date')
    doctor_id_filter = request.GET.get('doctor_id', 'ALL').strip()
    status_filter = (request.GET.get('status') or 'ALL').strip()

    try:
        db = get_db()
        
        # 1. Get all active admissions
        admissions = list(db['hospital_admission'].find({"is_cancelled": {"$ne": True}}))
        adm_by_ip = {a.get('ipNumber'): a for a in admissions if a.get('ipNumber')}
        
        # 2. Get billing records directly from hospital_dischargebilling
        billing_docs = list(db['hospital_dischargebilling'].find({"is_cancelled": {"$ne": True}}))
        billing_by_ip = {b.get('ip_number'): b for b in billing_docs if b.get('ip_number')}
        
        # 3. Get doctor fee cut records from hospital_doctorfeecuts
        fee_cut_query = {"is_active": {"$ne": False}}
        if status_filter and status_filter.upper() != 'ALL':
            fee_cut_query["status"] = status_filter

        fee_cuts = list(db['hospital_doctorfeecuts'].find(fee_cut_query))
        fee_cuts_by_ip = {f.get('ip_number'): f for f in fee_cuts if f.get('ip_number')}

        # 4. Collect all doctor IDs for employee name bulk resolution
        emp_ids = set()
        for b in billing_docs:
            for item in b.get('items', []):
                for doc in item.get('doctors', []):
                    for k, v in doc.items():
                        if k.endswith('_id') and v:
                            emp_ids.add(str(v).strip())

        for f in fee_cuts:
            for bd in f.get('doctor_breakdown', []):
                if bd.get('doctor_id'):
                    emp_ids.add(str(bd.get('doctor_id')).strip())

        emp_profile_map = _bulk_get_employee_profiles(emp_ids)

        # 5. Parse date boundaries
        from_dt = None
        to_dt = None
        if from_date_str:
            try:
                from_dt = datetime.datetime.strptime(from_date_str[:10], "%Y-%m-%d")
            except Exception:
                pass
        if to_date_str:
            try:
                to_dt = datetime.datetime.strptime(to_date_str[:10], "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            except Exception:
                pass

        # 6. Group by Doctor ID
        doctors_data = {}  # doctor_id -> { doctor_id, doctor_name, email, patients: [], total_billed, total_requested, total_approved }
        available_doctors_map = {}

        all_ip_numbers = set(list(billing_by_ip.keys()))

        for ip in all_ip_numbers:
            if ip not in billing_by_ip:
                continue
            adm = adm_by_ip.get(ip, {})
            bill = billing_by_ip.get(ip, {})
            claim = fee_cuts_by_ip.get(ip, {})

            status = claim.get('status', 'Pending') if claim else 'Pending'

            # Date check (DischargeBilling date)
            record_date_raw = claim.get('date') if claim else None
            if not record_date_raw:
                record_date_raw = bill.get('bill_date') or bill.get('created_date') or claim.get('approved_date') or adm.get('admissionDateTime')

            record_dt = None
            if isinstance(record_date_raw, (datetime.datetime, datetime.date)):
                record_dt = record_date_raw
            elif record_date_raw:
                try:
                    record_dt = datetime.datetime.fromisoformat(str(record_date_raw).replace("Z", "+00:00"))
                except Exception:
                    pass

            if from_dt and record_dt and record_dt.replace(tzinfo=None) < from_dt:
                continue
            if to_dt and record_dt and record_dt.replace(tzinfo=None) > to_dt:
                continue

            record_date_formatted = record_dt.strftime("%Y-%m-%d") if record_dt else str(record_date_raw or '')[:10]

            uhid = adm.get('uhid') or bill.get('uhid') or 'N/A'

            patient_name = (
                adm.get('patientName') or
                adm.get('patient_name') or
                bill.get('patient_name') or
                ""
            )
            if not patient_name and uhid and uhid != 'N/A':
                p_obj = db['hospital_patient'].find_one({"uhid": uhid})
                if p_obj:
                    patient_name = f"{p_obj.get('firstName', '')} {p_obj.get('lastName', '')}".strip()

            if not patient_name:
                patient_name = "N/A"

            customer_type = adm.get('customerType') or adm.get('customer_type') or bill.get('customer_type') or 'General'
            company_name = bill.get('company_name') or adm.get('insurance_company') or adm.get('company_name') or 'N/A'

            raw_doctors = _extract_raw_doctors_from_billing(bill)
            stored_bd = claim.get('doctor_breakdown', []) if claim else []

            stored_map = {}
            if isinstance(stored_bd, list):
                for s in stored_bd:
                    d_id = str(s.get('doctor_id', '')).strip()
                    r_role = str(s.get('role', '')).strip()
                    if d_id:
                        stored_map[(d_id, r_role)] = s

            processed_roles = set()
            doctors_to_process = []

            for d in raw_doctors:
                doc_id = d['id']
                role = d['role']
                bill_fee = d['fee']
                processed_roles.add((doc_id, role))
                stored_item = stored_map.get((doc_id, role)) or stored_map.get((doc_id, ''))
                req_fee = to_float(stored_item.get('requested_amount')) if (stored_item and stored_item.get('requested_amount') is not None) else 0.0
                app_fee = to_float(stored_item.get('approved_amount')) if (stored_item and stored_item.get('approved_amount') is not None) else 0.0
                doctors_to_process.append({
                    "doctor_id": doc_id,
                    "role": role,
                    "bill_fee": bill_fee,
                    "req_fee": req_fee,
                    "app_fee": app_fee
                })

            if isinstance(stored_bd, list):
                for s in stored_bd:
                    d_id = str(s.get('doctor_id', '')).strip()
                    r_role = str(s.get('role', '')).strip()
                    if d_id and (d_id, r_role) not in processed_roles:
                        req_fee = to_float(s.get('requested_amount'))
                        app_fee = to_float(s.get('approved_amount'))
                        doctors_to_process.append({
                            "doctor_id": d_id,
                            "role": r_role or "Doctor",
                            "bill_fee": 0.0,
                            "req_fee": req_fee,
                            "app_fee": app_fee
                        })

            for d in doctors_to_process:
                doc_id = d['doctor_id']
                role = d['role']
                bill_fee = d['bill_fee']
                req_fee = d['req_fee']
                app_fee = d['app_fee']

                prof = emp_profile_map.get(doc_id, {})
                doc_name = prof.get('name') or f"Doctor #{doc_id}"
                doc_email = prof.get('email', '').strip()

                available_doctors_map[doc_id] = {
                    "doctor_id": doc_id,
                    "doctor_name": doc_name,
                    "email": doc_email
                }

                if doctor_id_filter != 'ALL' and doctor_id_filter != doc_id:
                    continue

                if doc_id not in doctors_data:
                    doctors_data[doc_id] = {
                        "doctor_id": doc_id,
                        "doctor_name": doc_name,
                        "email": doc_email,
                        "total_billed": 0.0,
                        "total_requested": 0.0,
                        "total_approved": 0.0,
                        "patient_count": 0,
                        "patients": []
                    }

                doctors_data[doc_id]["total_billed"] += bill_fee
                doctors_data[doc_id]["total_requested"] += req_fee
                doctors_data[doc_id]["total_approved"] += app_fee
                doctors_data[doc_id]["patients"].append({
                    "date": record_date_formatted,
                    "ip_number": ip,
                    "uhid": uhid,
                    "patient_name": patient_name,
                    "customer_type": customer_type,
                    "company_name": company_name,
                    "role": role,
                    "billed_fee": bill_fee,
                    "requested_amount": req_fee,
                    "approved_amount": app_fee,
                    "status": status,
                    "email": doc_email,
                    "approved_by": claim.get('approved_by', '-') if claim else '-'
                })

        # Calculate distinct patient count per doctor and grand total of distinct patients
        all_unique_patients = set()
        for doc_item in doctors_data.values():
            unique_doc_ips = set(p['ip_number'] for p in doc_item['patients'] if p.get('ip_number'))
            doc_item['patient_count'] = len(unique_doc_ips)
            for p in doc_item['patients']:
                if p.get('ip_number'):
                    all_unique_patients.add(p['ip_number'])

        available_doctors = list(available_doctors_map.values())
        available_doctors.sort(key=lambda x: x['doctor_name'])

        doctorwise_list = list(doctors_data.values())
        doctorwise_list.sort(key=lambda x: x['doctor_name'])

        grand_totals = {
            "total_billed": sum(d['total_billed'] for d in doctorwise_list),
            "total_requested": sum(d['total_requested'] for d in doctorwise_list),
            "total_approved": sum(d['total_approved'] for d in doctorwise_list),
            "total_patients": len(all_unique_patients),
            "total_doctors": len(doctorwise_list)
        }

        return Response({
            "success": True,
            "data": {
                "available_doctors": available_doctors,
                "doctorwise_reports": doctorwise_list,
                "grand_totals": grand_totals
            }
        })

    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(['POST', 'GET'])
@permission_classes([HasRoleAndDataPermission])
def send_monthly_doctor_fee_cut_emails(request):
    """
    Sends HTML Doctor Fee Cut statement emails to individual doctors or custom recipient email.
    Supports:
    - Custom recipient email (custom_email) typed from UI.
    - Specific doctor filtering (doctor_id).
    - Custom date range (from_date, to_date).
    - Manual UI sending with force=True (bypasses duplicate checking).
    """
    try:
        data = request.data if request.method == 'POST' else (request.query_params or request.GET)

        custom_email = (data.get('custom_email') or request.GET.get('custom_email') or '').strip()
        doctor_id_filter = (data.get('doctor_id') or request.GET.get('doctor_id') or 'ALL').strip()
        status_filter = (data.get('status') or request.GET.get('status') or 'Approved').strip()
        force_send = data.get('force') in [True, 'true', '1', 1]

        from_date_str = data.get('from_date') or request.GET.get('from_date')
        to_date_str = data.get('to_date') or request.GET.get('to_date')

        today = timezone.now().date()

        if from_date_str and to_date_str:
            try:
                first_date = datetime.datetime.strptime(str(from_date_str)[:10], "%Y-%m-%d").date()
                last_date = datetime.datetime.strptime(str(to_date_str)[:10], "%Y-%m-%d").date()
                month_name = f"{first_date.strftime('%b %d, %Y')} to {last_date.strftime('%b %d, %Y')}"
            except Exception:
                first_date_current_month = today.replace(day=1)
                last_date = first_date_current_month - datetime.timedelta(days=1)
                first_date = last_date.replace(day=1)
                month_name = last_date.strftime("%B %Y")
        else:
            req_month = data.get('month') or request.GET.get('month')
            req_year = data.get('year') or request.GET.get('year')

            if req_month and req_year:
                m = int(req_month)
                y = int(req_year)
                first_date = datetime.date(y, m, 1)
                if m == 12:
                    next_first = datetime.date(y + 1, 1, 1)
                else:
                    next_first = datetime.date(y, m + 1, 1)
                last_date = next_first - datetime.timedelta(days=1)
            else:
                first_date_current_month = today.replace(day=1)
                last_date = first_date_current_month - datetime.timedelta(days=1)
                first_date = last_date.replace(day=1)

            month_name = last_date.strftime("%B %Y")

        from_dt = datetime.datetime.combine(first_date, datetime.time.min)
        to_dt = datetime.datetime.combine(last_date, datetime.time.max)

        db = get_db()

        fee_cut_query = {"is_active": {"$ne": False}}
        if status_filter and status_filter.upper() != 'ALL':
            fee_cut_query["status"] = status_filter

        fee_cuts = list(db['hospital_doctorfeecuts'].find(fee_cut_query))

        filtered_fee_cuts = []
        emp_ids = set()

        for f in fee_cuts:
            rec_date_raw = f.get('date') or f.get('approved_date') or f.get('created_date')
            rec_dt = None
            if isinstance(rec_date_raw, (datetime.datetime, datetime.date)):
                rec_dt = rec_date_raw
            elif rec_date_raw:
                try:
                    rec_dt = datetime.datetime.fromisoformat(str(rec_date_raw).replace("Z", "+00:00"))
                except Exception:
                    pass

            if rec_dt and (from_dt <= rec_dt.replace(tzinfo=None) <= to_dt):
                filtered_fee_cuts.append((f, rec_dt))
                for bd in f.get('doctor_breakdown', []):
                    if bd.get('doctor_id'):
                        emp_ids.add(str(bd.get('doctor_id')).strip())

        if not filtered_fee_cuts:
            return Response({
                "success": True,
                "message": f"No fee cut records found for selected criteria ({month_name})",
                "month_name": month_name,
                "sent_count": 0,
                "sent_details": [],
                "failed_details": []
            })

        emp_profiles = _bulk_get_employee_profiles(emp_ids)

        doctor_statements = {}

        billing_docs = list(db['hospital_dischargebilling'].find({"is_cancelled": {"$ne": True}}))
        billing_by_ip = {b.get('ip_number'): b for b in billing_docs if b.get('ip_number')}

        admissions = list(db['hospital_admission'].find({"is_cancelled": {"$ne": True}}))
        adm_by_ip = {a.get('ipNumber'): a for a in admissions if a.get('ipNumber')}

        for claim, rec_dt in filtered_fee_cuts:
            ip = claim.get('ip_number')
            uhid = claim.get('uhid', 'N/A')
            date_str = rec_dt.strftime("%Y-%m-%d")

            bill = billing_by_ip.get(ip, {})
            adm = adm_by_ip.get(ip, {})

            patient_name = adm.get('patientName') or adm.get('patient_name') or bill.get('patient_name') or ""
            if not patient_name and uhid and uhid != 'N/A':
                p_obj = db['hospital_patient'].find_one({"uhid": uhid})
                if p_obj:
                    patient_name = f"{p_obj.get('firstName', '')} {p_obj.get('lastName', '')}".strip()
            if not patient_name:
                patient_name = "N/A"

            for bd in claim.get('doctor_breakdown', []):
                doc_id = str(bd.get('doctor_id', '')).strip()
                if not doc_id:
                    continue

                if doctor_id_filter != 'ALL' and doctor_id_filter != doc_id:
                    continue

                profile = emp_profiles.get(doc_id, {})
                doc_name = profile.get('name') or f"Doctor #{doc_id}"
                doc_email = custom_email or profile.get('email', '').strip()

                req_amt = to_float(bd.get('requested_amount', 0.0))
                app_amt = to_float(bd.get('approved_amount', 0.0))
                role = str(bd.get('role', 'Doctor'))

                if doc_id not in doctor_statements:
                    doctor_statements[doc_id] = {
                        "doctor_id": doc_id,
                        "doctor_name": doc_name,
                        "email": doc_email,
                        "rows": [],
                        "total_requested": 0.0,
                        "total_approved": 0.0
                    }

                doctor_statements[doc_id]["rows"].append({
                    "date": date_str,
                    "patient_name": patient_name,
                    "uhid": uhid,
                    "ip_number": ip,
                    "role": role,
                    "requested_amount": req_amt,
                    "approved_amount": app_amt
                })
                doctor_statements[doc_id]["total_requested"] += req_amt
                doctor_statements[doc_id]["total_approved"] += app_amt

        sent_details = []
        failed_details = []
        skipped_details = []

        acc_email = getattr(settings, 'HMS_ACC_EMAIL', None) or os.getenv('HMS_ACC_EMAIL', 'najmasmrft@gmail.com')
        acc_password = getattr(settings, 'HMS_ACC_EMAIL_PASSWORD', None) or os.getenv('HMS_ACC_EMAIL_PASSWORD', 'zpid kdqk tekw ixjk')

        from django.core.mail import get_connection
        email_connection = get_connection(
            backend=getattr(settings, 'EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend'),
            host=getattr(settings, 'EMAIL_HOST', os.getenv('EMAIL_HOST', 'smtp.gmail.com')),
            port=int(getattr(settings, 'EMAIL_PORT', os.getenv('EMAIL_PORT', 587))),
            username=acc_email,
            password=acc_password,
            use_tls=getattr(settings, 'EMAIL_USE_TLS', True),
        )
        from_email = acc_email

        for doc_id, stmt in doctor_statements.items():
            doc_name = stmt["doctor_name"]
            to_email = custom_email or stmt["email"]
            rows = stmt["rows"]
            tot_req = stmt["total_requested"]
            tot_app = stmt["total_approved"]

            if not to_email:
                failed_details.append({
                    "doctor_id": doc_id,
                    "doctor_name": doc_name,
                    "reason": "No recipient email address provided or found in profile"
                })
                continue

            # Duplicate Check: Check if statement for this month was already logged in CommunicationLog
            if not force_send:
                already_sent = CommunicationLog.objects.filter(
                    template_name="doctor_fee_cut_monthly_statement",
                    patient_id=str(doc_id),
                    status="Success",
                    details__icontains=month_name
                ).exists()

                if already_sent:
                    skipped_details.append({
                        "doctor_id": doc_id,
                        "doctor_name": doc_name,
                        "email": to_email,
                        "reason": f"Statement email for {month_name} already sent to Dr. {doc_name}"
                    })
                    continue

            subject = f"Doctor Fee Cut Statement - {month_name} ({doc_name})"

            table_rows_html = ""
            for idx, r in enumerate(rows, 1):
                table_rows_html += f"""
                <tr>
                    <td style="padding: 8px; border: 1px solid #cbd5e1; text-align: center;">{idx}</td>
                    <td style="padding: 8px; border: 1px solid #cbd5e1;">{r['date']}</td>
                    <td style="padding: 8px; border: 1px solid #cbd5e1;">
                        <strong>{r['patient_name']}</strong><br>
                        <span style="color: #64748b; font-size: 11px;">IP: {r['ip_number']} | UHID: {r['uhid']}</span>
                    </td>
                    <td style="padding: 8px; border: 1px solid #cbd5e1;">{r['role']}</td>
                    <td style="padding: 8px; border: 1px solid #cbd5e1; text-align: right;">₹ {r['requested_amount']:,.2f}</td>
                    <td style="padding: 8px; border: 1px solid #cbd5e1; text-align: right; font-weight: bold; color: #0284c7;">₹ {r['approved_amount']:,.2f}</td>
                </tr>
                """

            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #334155; line-height: 1.6; background-color: #f8fafc; margin: 0; padding: 20px; }}
                    .card {{ max-width: 700px; margin: 0 auto; background: #ffffff; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); overflow: hidden; border: 1px solid #e2e8f0; }}
                    .header {{ background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%); color: #ffffff; padding: 20px 25px; text-align: center; }}
                    .header h2 {{ margin: 0; font-size: 20px; font-weight: 600; }}
                    .header p {{ margin: 5px 0 0 0; opacity: 0.9; font-size: 13px; }}
                    .body {{ padding: 25px; }}
                    table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 13px; }}
                    th {{ background-color: #f1f5f9; color: #1e293b; text-align: left; padding: 10px; border: 1px solid #cbd5e1; font-weight: 600; }}
                    .total-row {{ background-color: #f8fafc; font-weight: bold; font-size: 14px; }}
                    .footer {{ background-color: #f1f5f9; padding: 15px 25px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0; }}
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="header">
                        <h2>Shanmuga Hospital - Doctor Fee Cut Statement</h2>
                        <p>Approved Statement for <strong>{month_name}</strong></p>
                    </div>
                    <div class="body">
                        <p>Dear Dr. <strong>{doc_name}</strong>,</p>
                        <p>Please find below your approved Doctor Fee Cut summary for the month of <strong>{month_name}</strong>:</p>
                        
                        <table>
                            <thead>
                                <tr>
                                    <th style="width: 40px; text-align: center;">S.No</th>
                                    <th>Date</th>
                                    <th>Patient Details</th>
                                    <th>Role</th>
                                    <th style="text-align: right;">Requested Amount</th>
                                    <th style="text-align: right;">Approved Amount</th>
                                </tr>
                            </thead>
                            <tbody>
                                {table_rows_html}
                                <tr class="total-row">
                                    <td colspan="4" style="padding: 10px; border: 1px solid #cbd5e1; text-align: right;"><strong>Subtotal (Total Approved Income):</strong></td>
                                    <td style="padding: 10px; border: 1px solid #cbd5e1; text-align: right;">₹ {tot_req:,.2f}</td>
                                    <td style="padding: 10px; border: 1px solid #cbd5e1; text-align: right; color: #0284c7;"><strong>₹ {tot_app:,.2f}</strong></td>
                                </tr>
                            </tbody>
                        </table>

                        <p style="margin-top: 25px; font-size: 13px; color: #475569;">
                            If you have any questions or require further clarification regarding this statement, please contact the Shanmuga Hospital Accounts / Administration department.
                        </p>
                        <p style="font-size: 13px; color: #334155;">
                            Best regards,<br>
                            <strong>Shanmuga Hospital Administration</strong>
                        </p>
                    </div>
                    <div class="footer">
                        <p>This is an automated monthly statement. Please do not reply directly to this email.</p>
                    </div>
                </div>
            </body>
            </html>
            """

            hospital_code = request.headers.get("auth-hospital-code") or request.headers.get("hospital-code") or "SH001"
            branch_code = request.headers.get("Branch-Code") or request.headers.get("branch-code") or "SHB001"
            employee_id = request.headers.get("auth-user-id") or request.headers.get("user-id") or "system"

            try:
                msg = EmailMultiAlternatives(subject, f"Dear Dr. {doc_name},\nYour approved doctor fee cut total for {month_name} is Rs. {tot_app:.2f}.", from_email, [to_email], connection=email_connection)
                msg.attach_alternative(html_content, "text/html")
                msg.send(fail_silently=False)

                sent_details.append({
                    "doctor_id": doc_id,
                    "doctor_name": doc_name,
                    "email": to_email,
                    "total_approved": tot_app,
                    "patient_count": len(rows),
                    "status": "Sent"
                })

                # Store in CommunicationLog
                try:
                    CommunicationLog.objects.create(
                        patient_id=str(doc_id),
                        patient_name=f"Dr. {doc_name}",
                        type="Email",
                        sender=from_email,
                        recipient=to_email,
                        status="Success",
                        details=f"Doctor Fee Cut Statement for {month_name}. Total Approved: ₹{tot_app:,.2f}, Patients: {len(rows)}",
                        template_name="doctor_fee_cut_monthly_statement",
                        created_by=str(employee_id),
                        hospital_code=hospital_code,
                        branch_code=branch_code
                    )
                except Exception as log_err:
                    print(f"[NOTE] CommunicationLog creation error: {log_err}")

            except Exception as mail_err:
                print(f"[ERROR] Email send failed for {to_email}: {mail_err}")
                failed_details.append({
                    "doctor_id": doc_id,
                    "doctor_name": doc_name,
                    "email": to_email,
                    "error": str(mail_err)
                })

                # Store failure in CommunicationLog
                try:
                    CommunicationLog.objects.create(
                        patient_id=str(doc_id),
                        patient_name=f"Dr. {doc_name}",
                        type="Email",
                        sender=from_email,
                        recipient=to_email,
                        status="Failed",
                        details=f"Failed to send email: {str(mail_err)}",
                        template_name="doctor_fee_cut_monthly_statement",
                        created_by=str(employee_id),
                        hospital_code=hospital_code,
                        branch_code=branch_code
                    )
                except Exception as log_err:
                    print(f"[NOTE] CommunicationLog creation error: {log_err}")

        return Response({
            "success": True,
            "message": f"Sent {len(sent_details)} monthly doctor fee cut email(s) for {month_name}",
            "month_name": month_name,
            "sent_count": len(sent_details),
            "failed_count": len(failed_details),
            "sent_details": sent_details,
            "failed_details": failed_details
        })

    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)
