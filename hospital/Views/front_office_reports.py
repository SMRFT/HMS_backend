from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from datetime import datetime
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
def front_office_report_view(request):
    """
    Get various front office reports based on report_type.
    """
    try:
        report_type = request.GET.get('report_type')
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        doctor_name = request.GET.get('doctor_name', 'all')
        
        hospital_code = request.data.get('auth-hospital-code', 'system')
        branch_code = request.data.get('auth-branch-code', 'system')

        if not start_date_str or not end_date_str:
            return Response({"error": "start_date and end_date are required"}, status=400)
        
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        
        doctor_map = get_doctor_mapping(client)
        def resolve_doc_name(val):
            if not val: return val
            return doctor_map.get(val, val)

        results = []

        if report_type == 'referred_patients' or report_type == 'op_patients':
            query = {
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "created_date": {"$gte": start_date, "$lte": end_date}
            }
            if report_type == 'referred_patients':
                query["referredBy"] = {"$exists": True, "$ne": None, "$ne": ""}
            
            patients = list(db['hospital_patient'].find(query).sort("created_date", 1))
            for p in patients:
                p['doctorName'] = resolve_doc_name(p.get('doctorName'))
                results.append(p)

        elif report_type == 'admission_register' or report_type == 'doctor_wise_admission':
            query = {
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "admissionDateTime": {"$gte": start_date, "$lte": end_date}
            }
            # If searching by name, we might need to handle both name and ID in query if doctor_name is a name
            if doctor_name and doctor_name.lower() != 'all':
                # Find ID for this name if possible
                doc_id = next((k for k, v in doctor_map.items() if v == doctor_name), None)
                if doc_id:
                    query["$or"] = [{"admittingDoctor": doctor_name}, {"admittingDoctor": doc_id}]
                else:
                    query["admittingDoctor"] = doctor_name
                
            admissions = list(db['hospital_admission'].find(query).sort("admissionDateTime", 1))
            
            uhids = [a.get('uhid') for a in admissions]
            patients = {p['uhid']: f"{p.get('firstName', '')} {p.get('lastName', '')}" 
                        for p in db['hospital_patient'].find({"uhid": {"$in": uhids}})}
            
            for a in admissions:
                a['patient_name'] = patients.get(a.get('uhid'), 'Unknown')
                a['admittingDoctor'] = resolve_doc_name(a.get('admittingDoctor'))
                a['consultingDoctor'] = resolve_doc_name(a.get('consultingDoctor'))
                results.append(a)

        elif report_type == 'discharge_register':
            query = {
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "dod": {"$gte": start_date.date().isoformat(), "$lte": end_date.date().isoformat()},
                "is_active": True
            }
            summaries = list(db['hospital_summary'].find(query).sort("dod", 1))
            
            ip_numbers = [r.get('ipNo') for r in summaries]
            admissions = {a['ipNumber']: a for a in db['hospital_admission'].find({"ipNumber": {"$in": ip_numbers}})}
            
            for r in summaries:
                adm = admissions.get(r.get('ipNo'), {})
                r['admission_date'] = adm.get('admissionDateTime')
                r['admitting_doctor'] = resolve_doc_name(adm.get('admittingDoctor'))
                
                p = db['hospital_patient'].find_one({"uhid": r.get('uhid')})
                if p:
                    r['patient_name'] = f"{p.get('firstName', '')} {p.get('lastName', '')}"
                results.append(r)

        elif report_type == 'new_born_babies':
            query = {
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "created_date": {"$gte": start_date, "$lte": end_date},
                "mothers_uhid_no": {"$exists": True, "$ne": None, "$ne": ""}
            }
            babies = list(db['hospital_patient'].find(query).sort("created_date", 1))
            for b in babies:
                b['pediatrician_responsible'] = resolve_doc_name(b.get('pediatrician_responsible'))
                results.append(b)

        elif report_type == 'doctor_wise_ip_collection':
            # DischargeBilling.bill_date is a DateField and is persisted as an
            # ISO date string ("YYYY-MM-DD"), not a BSON datetime — compare as
            # strings (same convention used in advanced_dashboard.py).
            query = {
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "bill_date": {"$gte": start_date.date().isoformat(), "$lte": end_date.date().isoformat()},
                "status": "Billed",
                "is_active": True
            }
            billings = list(db['hospital_dischargebilling'].find(query))
            
            doctor_stats = {}
            for bill in billings:
                items = bill.get('items', [])
                for item in items:
                    doc_val = item.get('doctor')
                    if not doc_val: continue
                    
                    doc_name_resolved = resolve_doc_name(doc_val)
                    
                    if doctor_name and doctor_name.lower() != 'all' and doc_name_resolved != doctor_name:
                        continue
                        
                    if doc_name_resolved not in doctor_stats:
                        doctor_stats[doc_name_resolved] = {
                            "doctor_name": doc_name_resolved,
                            "total_collection": 0,
                            "bill_count": 0,
                            "patients": set()
                        }
                    
                    doctor_stats[doc_name_resolved]["total_collection"] += float(serialize_doc(item.get('amount', 0)) or 0)
                    doctor_stats[doc_name_resolved]["bill_count"] += 1
                    doctor_stats[doc_name_resolved]["patients"].add(bill.get('uhid'))
            
            for doc in doctor_stats:
                doctor_stats[doc]["patient_count"] = len(doctor_stats[doc]["patients"])
                del doctor_stats[doc]["patients"]
                results.append(doctor_stats[doc])

        client.close()
        return Response(serialize_doc(results), status=200)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)
