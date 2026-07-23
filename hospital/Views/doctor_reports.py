from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from datetime import datetime, timedelta
from pyauth.auth import HasRoleAndDataPermission
from bson import Decimal128, ObjectId

def serialize_doc(doc):
    if isinstance(doc, dict):
        return {k: serialize_doc(v) for k, v in doc.items()}
    elif isinstance(doc, list):
        return [serialize_doc(i) for i in doc]
    elif isinstance(doc, Decimal128):
        return float(doc.to_decimal())
    elif isinstance(doc, ObjectId):
        return str(doc)
    elif isinstance(doc, datetime):
        return doc.isoformat()
    return doc

def get_doctor_mapping(client):
    try:
        global_db = client['Global']
        diagnostics_collection = global_db['backend_diagnostics_profile']
        doctors = list(diagnostics_collection.find(
            {"designation": "DESIG094"},
            {"employeeId": 1, "employeeName": 1, "_id": 0}
        ))
        return {d['employeeId']: d['employeeName'] for d in doctors if d.get('employeeId')}
    except:
        return {}

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def doctor_report_view(request):
    """
    Get doctor day-wise or month-wise report for admissions and billing.
    Query params:
    - doctor_name: employeeName of the doctor (string), or 'all'
    - start_date: YYYY-MM-DD
    - end_date: YYYY-MM-DD
    - report_type: 'day' or 'month'
    """
    try:
        doctor_name = request.GET.get('doctor_name')
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        report_type = request.GET.get('report_type', 'day') # 'day' or 'month'

        hospital_code = request.data.get('auth-hospital-code', 'system')
        branch_code = request.data.get('auth-branch-code', 'system')

        if not start_date_str or not end_date_str:
            return Response({"error": "start_date and end_date are required"}, status=400)

        is_all_doctors = not doctor_name or doctor_name.lower() == 'all'

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']

        # admittingDoctor / consultingDoctor / Billing.doctor_id / invest "doctor" /
        # discharge item "doctor" all store the doctor's employeeId, but the
        # frontend sends the doctor's employeeName — resolve name -> id here so
        # the filters below actually match, instead of silently returning nothing.
        doctor_map = get_doctor_mapping(client)
        doctor_id = None
        if not is_all_doctors:
            doctor_id = next((k for k, v in doctor_map.items() if v == doctor_name), None)
            if not doctor_id:
                # Not found by name — maybe an id was passed directly (e.g. old link)
                doctor_id = doctor_name

        def resolve_doc_name(val):
            if not val: return val
            return doctor_map.get(val, val)

        # 1. Fetch Admissions
        admission_query = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "admissionDateTime": {"$gte": start_date, "$lte": end_date}
        }
        if not is_all_doctors:
            admission_query["$or"] = [
                {"admittingDoctor": doctor_id},
                {"consultingDoctor": doctor_id}
            ]
        admissions = list(db['hospital_admission'].find(admission_query))

        # 2. Fetch Billings (OP consultation) — only realized (Paid) revenue
        billing_query = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "billed_date": {"$gte": start_date, "$lte": end_date},
            "payment_status": "Paid"
        }
        if not is_all_doctors:
            billing_query["doctor_id"] = doctor_id
        reg_billings = list(db['hospital_billing'].find(billing_query))

        # 3. Fetch Investigation Billings — only realized (Paid) revenue
        invest_query = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "investBillDate": {"$gte": start_date, "$lte": end_date},
            "paymentStatus": "Paid"
        }
        if not is_all_doctors:
            invest_query["doctor"] = doctor_id
        invest_billings = list(db['hospital_investbilling'].find(invest_query))

        # 4. Fetch Discharge Billings — only finalized (Billed) bills
        discharge_query = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            # DischargeBilling.bill_date is a DateField, persisted as an ISO
            # date string ("YYYY-MM-DD"), not a BSON datetime.
            "bill_date": {"$gte": start_date.date().isoformat(), "$lte": end_date.date().isoformat()},
            "status": "Billed",
            "is_active": True
        }
        discharge_billings = list(db['hospital_dischargebilling'].find(discharge_query))

        # 5. Resolve bill-type names for investigation bills (bill_name isn't
        # stored on the invest-bill document itself — it lives on hospital_billtype)
        bill_type_ids = set()
        for b in invest_billings:
            try:
                bill_type_ids.add(int(b.get("bill_type")))
            except (TypeError, ValueError):
                pass
        bill_type_map = {}
        if bill_type_ids:
            bt_docs = db['hospital_billtype'].find(
                {"bill_type": {"$in": list(bill_type_ids)}},
                {"_id": 0, "bill_type": 1, "bill_name": 1}
            )
            bill_type_map = {int(bt["bill_type"]): bt.get("bill_name", "") for bt in bt_docs}

        # 6. Resolve patient names.
        # Admission/Investigation/Discharge bills carry the patient's `uhid`.
        # Billing (OP) instead carries a raw FK `patient_id` pointing at the
        # Patient row's own `id` field — different join key entirely.
        uhids = set()
        for a in admissions:
            if a.get('uhid'): uhids.add(a['uhid'])
        for b in invest_billings:
            if b.get('uhid'): uhids.add(b['uhid'])
        for b in discharge_billings:
            if b.get('uhid'): uhids.add(b['uhid'])

        patient_ids = set()
        for b in reg_billings:
            if b.get('patient_id') is not None: patient_ids.add(b['patient_id'])

        patients_by_uhid = {}
        patients_by_id = {}
        if uhids or patient_ids:
            or_clauses = []
            if uhids: or_clauses.append({"uhid": {"$in": list(uhids)}})
            if patient_ids: or_clauses.append({"id": {"$in": list(patient_ids)}})
            for p in db['hospital_patient'].find({"$or": or_clauses}):
                name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
                if p.get('uhid'): patients_by_uhid[p['uhid']] = name
                if p.get('id') is not None: patients_by_id[p['id']] = {"name": name, "uhid": p.get('uhid')}

        # 7. Aggregate Data
        report_data = []

        for adm in admissions:
            dt = adm.get('admissionDateTime')
            key = dt.strftime('%Y-%m-%d') if report_type == 'day' else dt.strftime('%Y-%m')
            doc_id_val = adm.get('admittingDoctor') or adm.get('consultingDoctor')
            report_data.append({
                "date": key,
                "type": "Admission",
                "doctor": resolve_doc_name(doc_id_val),
                "patient_name": patients_by_uhid.get(adm.get('uhid'), 'Unknown'),
                "uhid": adm.get('uhid'),
                "ip_number": adm.get('ipNumber'),
                "amount": 0,
                "details": adm.get('reasonForAdmission', '')
            })

        for bill in reg_billings:
            dt = bill.get('billed_date')
            key = dt.strftime('%Y-%m-%d') if report_type == 'day' else dt.strftime('%Y-%m')
            patient_info = patients_by_id.get(bill.get('patient_id'), {})
            report_data.append({
                "date": key,
                "type": "Registration Bill",
                "doctor": resolve_doc_name(bill.get('doctor_id')),
                "patient_name": patient_info.get('name', 'Unknown'),
                "uhid": patient_info.get('uhid'),
                "ip_number": "",
                "amount": float(str(bill.get('consulting_fee') or bill.get('total_fees') or 0)),
                "details": "Registration"
            })

        for bill in invest_billings:
            dt = bill.get('investBillDate')
            key = dt.strftime('%Y-%m-%d') if report_type == 'day' else dt.strftime('%Y-%m')
            try:
                bt_name = bill_type_map.get(int(bill.get('bill_type')), '')
            except (TypeError, ValueError):
                bt_name = ''
            report_data.append({
                "date": key,
                "type": "Investigation Bill",
                "doctor": resolve_doc_name(bill.get('doctor')),
                "patient_name": patients_by_uhid.get(bill.get('uhid'), 'Unknown'),
                "uhid": bill.get('uhid'),
                "ip_number": bill.get('ipNumber', ''),
                "amount": float(str(bill.get('finalPrice') or 0)),
                "details": bt_name
            })

        for bill in discharge_billings:
            dt = bill.get('bill_date')
            if isinstance(dt, datetime):
                dt_obj = dt
            elif isinstance(dt, str):
                try:
                    dt_obj = datetime.strptime(dt[:10], '%Y-%m-%d')
                except ValueError:
                    dt_obj = None
            else:
                dt_obj = datetime.combine(dt, datetime.min.time()) if dt else None

            if not dt_obj: continue

            key = dt_obj.strftime('%Y-%m-%d') if report_type == 'day' else dt_obj.strftime('%Y-%m')

            items = bill.get('items', [])
            if is_all_doctors:
                doctor_items = items
            else:
                doctor_items = [item for item in items if item.get('doctor') == doctor_id]

            if doctor_items:
                doctor_amount = sum(float(str(serialize_doc(item.get('doctor_fee') or item.get('amount') or 0))) for item in doctor_items)
                doc_names = sorted(set(resolve_doc_name(i.get('doctor')) for i in doctor_items if i.get('doctor')))
                report_data.append({
                    "date": key,
                    "type": "Discharge Bill",
                    "doctor": ", ".join(doc_names),
                    "patient_name": patients_by_uhid.get(bill.get('uhid'), 'Unknown'),
                    "uhid": bill.get('uhid'),
                    "ip_number": bill.get('ip_number', ''),
                    "amount": doctor_amount,
                    "details": f"Discharge Bill Items: {', '.join([i.get('itemName', '') for i in doctor_items])}"
                })

        # 8. Group by date
        grouped_data = {}
        for item in report_data:
            key = item['date']
            if key not in grouped_data:
                grouped_data[key] = {
                    "date": key,
                    "admissions": 0,
                    "billings": 0,
                    "total_amount": 0,
                    "items": []
                }

            if item['type'] == 'Admission':
                grouped_data[key]['admissions'] += 1
            else:
                grouped_data[key]['billings'] += 1
                grouped_data[key]['total_amount'] += float(serialize_doc(item['amount']) or 0)

            grouped_data[key]['items'].append(item)

        # Convert back to list and sort
        final_report = list(grouped_data.values())
        final_report.sort(key=lambda x: x['date'])

        client.close()
        return Response(serialize_doc(final_report), status=200)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)
