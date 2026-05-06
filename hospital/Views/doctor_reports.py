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

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def doctor_report_view(request):
    """
    Get doctor day-wise or month-wise report for admissions and billing.
    Query params:
    - doctor_name: Name of the doctor (string)
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
        
        # 1. Fetch Admissions
        admission_query = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "admissionDateTime": {"$gte": start_date, "$lte": end_date}
        }
        if not is_all_doctors:
            admission_query["$or"] = [
                {"admittingDoctor": doctor_name},
                {"consultingDoctor": doctor_name}
            ]
        admissions = list(db['hospital_admission'].find(admission_query))
        
        # 2. Fetch Billings
        billing_query = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "billed_date": {"$gte": start_date, "$lte": end_date}
        }
        if not is_all_doctors:
            billing_query["doctor_id"] = doctor_name
        reg_billings = list(db['hospital_billing'].find(billing_query))
        
        invest_query = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "investBillDate": {"$gte": start_date, "$lte": end_date}
        }
        if not is_all_doctors:
            invest_query["doctor"] = doctor_name
        invest_billings = list(db['hospital_investbilling'].find(invest_query))

        # 3. Fetch Discharge Billings
        discharge_query = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "bill_date": {"$gte": start_date, "$lte": end_date},
            "is_active": True
        }
        discharge_billings = list(db['hospital_dischargebilling'].find(discharge_query))

        # 4. Aggregate Data
        report_data = []
        
        for adm in admissions:
            dt = adm.get('admissionDateTime')
            key = dt.strftime('%Y-%m-%d') if report_type == 'day' else dt.strftime('%Y-%m')
            report_data.append({
                "date": key,
                "type": "Admission",
                "doctor": adm.get('admittingDoctor') or adm.get('consultingDoctor'),
                "patient_name": f"{adm.get('firstName', '')} {adm.get('lastName', '')}",
                "uhid": adm.get('uhid'),
                "ip_number": adm.get('ipNumber'),
                "amount": 0,
                "details": adm.get('reasonForAdmission', '')
            })
            
        for bill in reg_billings:
            dt = bill.get('billed_date')
            key = dt.strftime('%Y-%m-%d') if report_type == 'day' else dt.strftime('%Y-%m')
            report_data.append({
                "date": key,
                "type": "Registration Bill",
                "doctor": bill.get('doctor_id'),
                "patient_name": bill.get('patient_name'),
                "uhid": bill.get('uhid'),
                "ip_number": "",
                "amount": bill.get('total_fees', 0),
                "details": "Registration"
            })
            
        for bill in invest_billings:
            dt = bill.get('investBillDate')
            key = dt.strftime('%Y-%m-%d') if report_type == 'day' else dt.strftime('%Y-%m')
            report_data.append({
                "date": key,
                "type": "Investigation Bill",
                "doctor": bill.get('doctor'),
                "patient_name": f"{bill.get('firstName', '')} {bill.get('lastName', '')}",
                "uhid": bill.get('uhid'),
                "ip_number": bill.get('ipNumber'),
                "amount": bill.get('netAmount', 0),
                "details": bill.get('bill_name', '')
            })

        for bill in discharge_billings:
            dt = bill.get('bill_date')
            if isinstance(dt, datetime):
                dt_obj = dt
            else:
                dt_obj = datetime.combine(dt, datetime.min.time()) if dt else None
            
            if not dt_obj: continue
            
            key = dt_obj.strftime('%Y-%m-%d') if report_type == 'day' else dt_obj.strftime('%Y-%m')
            
            items = bill.get('items', [])
            if is_all_doctors:
                doctor_items = items
            else:
                doctor_items = [item for item in items if item.get('doctor') == doctor_name]
            
            if doctor_items:
                doctor_amount = sum(float(serialize_doc(item.get('amount', 0)) or 0) for item in doctor_items)
                report_data.append({
                    "date": key,
                    "type": "Discharge Bill",
                    "doctor": ", ".join(list(set([i.get('doctor') for i in doctor_items if i.get('doctor')]))),
                    "patient_name": bill.get('uhid'),
                    "uhid": bill.get('uhid'),
                    "ip_number": bill.get('ipNumber'),
                    "amount": doctor_amount,
                    "details": f"Discharge Bill Items: {', '.join([i.get('itemName', '') for i in doctor_items])}"
                })

        # 5. Group by date
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
