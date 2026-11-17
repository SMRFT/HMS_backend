from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from datetime import datetime
from pyauth.auth import HasRoleAndDataPermission
from bson import Decimal128, ObjectId

_mongo_client = None

def get_mongo_client():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    return _mongo_client

def serialize_doc(doc):
    if isinstance(doc, dict):
        return {k: serialize_doc(v) for k, v in doc.items()}
    elif isinstance(doc, list):
        return [serialize_doc(i) for i in doc]
    elif isinstance(doc, Decimal128):
        try:
            return float(doc.to_decimal())
        except Exception:
            return float(str(doc))
    elif isinstance(doc, ObjectId):
        return str(doc)
    elif isinstance(doc, datetime):
        return doc.isoformat()
    return doc

def _safe_num(val):
    if val is None:
        return 0.0
    if isinstance(val, Decimal128):
        try:
            return float(val.to_decimal())
        except Exception:
            return float(str(val))
    try:
        return float(val)
    except Exception:
        return 0.0

def get_doctor_mapping():
    try:
        client = get_mongo_client()
        diagnostics_collection = client['Global']['backend_diagnostics_profile']
        doctor_query = {
            "$or": [
                {"designation": "DESIG094"},
                {"primaryRole": "SD-R-DOC"},
                {"additionalRoles": "SD-R-DOC"},
                {"employeeName": {"$regex": r"^\s*Dr", "$options": "i"}}
            ]
        }
        doctors = list(diagnostics_collection.find(
            doctor_query,
            {"employeeId": 1, "employeeName": 1, "_id": 0}
        ))
        return {str(d['employeeId']): d['employeeName'] for d in doctors if d.get('employeeId')}
    except Exception:
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
        
        auth_data = getattr(request, 'data', {}) if request.method != 'GET' else {}
        hospital_code = (
            auth_data.get('auth-hospital-code') or 
            request.headers.get('Hospital-Code') or 
            request.GET.get('hospital_code') or 
            'SH001'
        )
        branch_code = (
            auth_data.get('auth-branch-code') or 
            request.headers.get('Branch-Code') or 
            request.GET.get('branch_code') or 
            'SHB001'
        )

        if not start_date_str or not end_date_str:
            return Response({"error": "start_date and end_date are required"}, status=400)
        
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

        client = get_mongo_client()
        db = client['HMS']
        doctor_map = get_doctor_mapping()
        def resolve_doc_name(val):
            if not val: return val
            return doctor_map.get(str(val).strip(), str(val).strip())

        results = []

        if report_type == 'op_patients':
            visit_type_filter = request.GET.get('visit_type', 'all').lower()  # 'all', 'new', 'renew'

            # 1. Fetch OP Bills in range
            bill_query = {
                "hospital_code": {"$in": [hospital_code, None, "system"]},
                "branch_code": branch_code,
                "$or": [
                    {"billed_date": {"$gte": start_date, "$lte": end_date}},
                    {"billed_date": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}},
                    {"created_date": {"$gte": start_date, "$lte": end_date}}
                ]
            }
            bills = list(db['hospital_billing'].find(bill_query).sort("billed_date", -1))
            b_uhids = [b.get('uhid') for b in bills if b.get('uhid')]

            # 2. Fetch new registrations in range
            pt_query = {
                "hospital_code": {"$in": [hospital_code, None, "system"]},
                "branch_code": branch_code,
                "$or": [
                    {"created_date": {"$gte": start_date, "$lte": end_date}},
                    {"created_date": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}},
                    {"registration_date": {"$gte": start_date_str, "$lte": end_date_str}}
                ]
            }
            new_patients_list = list(db['hospital_patient'].find(pt_query))
            new_uhid_set = set([p.get('uhid') for p in new_patients_list if p.get('uhid')])

            all_uhids = list(set(b_uhids + list(new_uhid_set)))
            patients_map = {p['uhid']: p for p in db['hospital_patient'].find({"uhid": {"$in": all_uhids}})}

            seen_bills = set()
            for b in bills:
                u = b.get('uhid')
                pt = patients_map.get(u, {})
                bd = b.get('billed_date') or b.get('created_date')
                cd = pt.get('created_date') or pt.get('registration_date')

                is_new = False
                if u in new_uhid_set:
                    is_new = True
                elif cd and bd:
                    if isinstance(cd, datetime) and isinstance(bd, datetime):
                        is_new = (cd.date() == bd.date())
                    elif isinstance(cd, str) and isinstance(bd, datetime):
                        is_new = cd.startswith(bd.strftime("%Y-%m-%d"))
                    elif _safe_num(b.get('registration_fee')) > 0:
                        is_new = True
                elif _safe_num(b.get('registration_fee')) > 0:
                    is_new = True

                reg_type = "NEW" if is_new else "RENEW"

                if visit_type_filter == 'new' and not is_new:
                    continue
                if visit_type_filter == 'renew' and is_new:
                    continue

                doc_val = b.get('doctor_id') or pt.get('doctorName')
                doc_name_resolved = resolve_doc_name(doc_val)

                if doctor_name and doctor_name.lower() != 'all':
                    if (doc_name_resolved or "").strip().lower() != doctor_name.strip().lower():
                        continue

                p_name = f"{pt.get('salutation', '')} {pt.get('firstName', '')} {pt.get('lastName', '')}".strip() or pt.get('name') or "N/A"
                results.append({
                    "uhid": u,
                    "bill_number": b.get('bill_number') or '-',
                    "patient_name": p_name,
                    "age": pt.get('age') or '-',
                    "gender": pt.get('gender') or '-',
                    "mobilePhone": pt.get('mobilePhone') or '-',
                    "created_date": bd,
                    "reg_type": reg_type,
                    "is_new": is_new,
                    "registration_fee": _safe_num(b.get('registration_fee')),
                    "consulting_fee": _safe_num(b.get('consulting_fee')),
                    "total_fees": _safe_num(b.get('total_fees')),
                    "referredBy": pt.get('referredBy') or 'Direct',
                    "doctorName": doc_name_resolved or 'N/A'
                })
                if u: seen_bills.add(u)

            # Append new patients who haven't billed yet
            if visit_type_filter != 'renew':
                for p in new_patients_list:
                    u = p.get('uhid')
                    if u and u in seen_bills:
                        continue
                    doc_val = p.get('doctorName')
                    doc_name_resolved = resolve_doc_name(doc_val)
                    if doctor_name and doctor_name.lower() != 'all':
                        if (doc_name_resolved or "").strip().lower() != doctor_name.strip().lower():
                            continue
                    p_name = f"{p.get('salutation', '')} {p.get('firstName', '')} {p.get('lastName', '')}".strip() or p.get('name') or "N/A"
                    results.append({
                        "uhid": u,
                        "bill_number": "-",
                        "patient_name": p_name,
                        "age": p.get('age') or '-',
                        "gender": p.get('gender') or '-',
                        "mobilePhone": p.get('mobilePhone') or '-',
                        "created_date": p.get('created_date') or p.get('registration_date'),
                        "reg_type": "NEW",
                        "is_new": True,
                        "registration_fee": 0.0,
                        "consulting_fee": 0.0,
                        "total_fees": 0.0,
                        "referredBy": p.get('referredBy') or 'Direct',
                        "doctorName": doc_name_resolved or 'N/A'
                    })

        elif report_type == 'referred_patients':
            visit_type_filter = request.GET.get('visit_type', 'all').lower()
            query = {
                "hospital_code": {"$in": [hospital_code, None, "system"]},
                "branch_code": branch_code,
                "$or": [
                    {"created_date": {"$gte": start_date, "$lte": end_date}},
                    {"created_date": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}},
                    {"registration_date": {"$gte": start_date_str, "$lte": end_date_str}}
                ],
                "referredBy": {"$nin": [None, "", "null", "undefined", "-"]}
            }
            patients = list(db['hospital_patient'].find(query).sort("created_date", -1))
            for p in patients:
                resolved_doc = resolve_doc_name(p.get('doctorName'))
                p['doctorName'] = resolved_doc
                p['reg_type'] = "NEW"
                p['is_new'] = True
                if doctor_name and doctor_name.lower() != 'all':
                    if (resolved_doc or "").strip().lower() != doctor_name.strip().lower():
                        continue
                results.append(p)

        elif report_type == 'admission_register' or report_type == 'doctor_wise_admission':
            query = {
                "hospital_code": {"$in": [hospital_code, None, "system"]},
                "branch_code": branch_code,
                "$or": [
                    {"admissionDateTime": {"$gte": start_date, "$lte": end_date}},
                    {"admissionDateTime": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}}
                ]
            }
            if doctor_name and doctor_name.lower() != 'all':
                doc_id = next((k for k, v in doctor_map.items() if v.lower() == doctor_name.lower()), None)
                if doc_id:
                    query["$or"] = [{"admittingDoctor": doctor_name}, {"admittingDoctor": doc_id}]
                else:
                    query["admittingDoctor"] = doctor_name
                
            admissions = list(db['hospital_admission'].find(query).sort("admissionDateTime", -1))
            
            uhids = [a.get('uhid') for a in admissions if a.get('uhid')]
            patients = {p['uhid']: f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or p.get('name', '')
                        for p in db['hospital_patient'].find({"uhid": {"$in": uhids}})}
            
            for a in admissions:
                a['patient_name'] = patients.get(a.get('uhid')) or a.get('patientName') or 'Unknown'
                a['admittingDoctor'] = resolve_doc_name(a.get('admittingDoctor'))
                a['consultingDoctor'] = resolve_doc_name(a.get('consultingDoctor'))
                # Extract current active room if present
                active_room = None
                active_bed = None
                for rm in a.get('roomShitingDetails', []) or []:
                    if rm.get('is_roomActive'):
                        active_room = rm.get('newRoomNo')
                        active_bed = rm.get('newBedNo')
                if not active_room:
                    for rm in a.get('room_details', []) or []:
                        if rm.get('is_roomActive'):
                            active_room = rm.get('roomNo')
                            active_bed = rm.get('bedNo')
                if not active_room and a.get('room_details'):
                    first_rm = a['room_details'][0]
                    active_room = first_rm.get('roomNo')
                    active_bed = first_rm.get('bedNo')
                a['roomNo'] = active_room or '-'
                a['bedNo'] = active_bed or '-'
                results.append(a)

        elif report_type == 'discharge_register':
            # Query hospital_dischargebilling for accurate, comprehensive discharge registry
            billing_query = {
                "hospital_code": {"$in": [hospital_code, None, "system"]},
                "branch_code": branch_code,
                "$or": [
                    {"bill_date": {"$gte": start_date, "$lte": end_date}},
                    {"bill_date": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}},
                    {"created_date": {"$gte": start_date, "$lte": end_date}}
                ],
                "is_cancelled": {"$ne": True}
            }
            discharge_bills = list(db['hospital_dischargebilling'].find(billing_query).sort("bill_date", -1))
            
            ip_numbers = [b.get('ip_number') or b.get('ipNumber') for b in discharge_bills if (b.get('ip_number') or b.get('ipNumber'))]
            uhids = [b.get('uhid') for b in discharge_bills if b.get('uhid')]
            
            admissions_map = {}
            if ip_numbers:
                for adm in db['hospital_admission'].find({"$or": [{"ipNumber": {"$in": ip_numbers}}, {"ip_number": {"$in": ip_numbers}}]}):
                    ip_k = adm.get("ipNumber") or adm.get("ip_number")
                    if ip_k:
                        admissions_map[ip_k] = adm
                        
            patients_map = {}
            if uhids:
                for pt in db['hospital_patient'].find({"uhid": {"$in": uhids}}):
                    p_name = f"{pt.get('salutation', '')} {pt.get('firstName', '')} {pt.get('lastName', '')}".strip() or pt.get("name", "")
                    patients_map[pt.get("uhid")] = {
                        "name": p_name,
                        "age": pt.get("age"),
                        "gender": pt.get("gender"),
                        "mobilePhone": pt.get("mobilePhone") or pt.get("mobile_phone") or pt.get("mobile")
                    }
            
            seen_ips = set()
            for b in discharge_bills:
                ip_num = b.get('ip_number') or b.get('ipNumber') or 'N/A'
                if ip_num != 'N/A' and ip_num in seen_ips:
                    continue
                if ip_num != 'N/A':
                    seen_ips.add(ip_num)
                    
                u_id = b.get('uhid')
                adm = admissions_map.get(ip_num, {})
                pt = patients_map.get(u_id, {})
                
                item_doc = (b.get('items', [{}])[0].get('doctor') if b.get('items') else None)
                doc_val = b.get('doctor') or adm.get('admittingDoctor') or adm.get('consultingDoctor') or item_doc or 'Hospital Service'
                doc_name_resolved = resolve_doc_name(doc_val)
                
                if doctor_name and doctor_name.lower() != 'all':
                    if (doc_name_resolved or "").strip().lower() != doctor_name.strip().lower():
                        continue

                mob = pt.get("mobilePhone") or adm.get("mobileNumber") or adm.get("mobile") or adm.get("contactNumber") or b.get("mobile") or '-'
                        
                results.append({
                    "ipNo": ip_num,
                    "uhid": u_id,
                    "patient_name": pt.get("name") or adm.get("patientName") or "Patient",
                    "age": pt.get("age") or adm.get("age") or '-',
                    "gender": pt.get("gender") or adm.get("gender") or '-',
                    "mobile": mob,
                    "admission_date": adm.get("admissionDateTime") or b.get("doa"),
                    "dod": b.get("bill_date") or b.get("created_date"),
                    "admitting_doctor": doc_name_resolved,
                    "bill_no": b.get("bill_no"),
                    "net_amount": _safe_num(b.get("net_amount") or b.get("total_amount") or 0)
                })

        elif report_type == 'new_born_babies':
            query = {
                "hospital_code": {"$in": [hospital_code, None, "system"]},
                "branch_code": branch_code,
                "$or": [
                    {"created_date": {"$gte": start_date, "$lte": end_date}},
                    {"created_date": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}},
                    {"registration_date": {"$gte": start_date_str, "$lte": end_date_str}}
                ],
                "mothers_uhid_no": {"$nin": [None, "", "null", "undefined", "-"]}
            }
            babies = list(db['hospital_patient'].find(query).sort("created_date", -1))
            for b in babies:
                b['pediatrician_responsible'] = resolve_doc_name(b.get('pediatrician_responsible'))
                results.append(b)

        elif report_type == 'doctor_wise_ip_collection':
            query = {
                "hospital_code": {"$in": [hospital_code, None, "system"]},
                "branch_code": branch_code,
                "$or": [
                    {"bill_date": {"$gte": start_date, "$lte": end_date}},
                    {"bill_date": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}},
                    {"created_date": {"$gte": start_date, "$lte": end_date}}
                ],
                "is_cancelled": {"$ne": True}
            }
            billings = list(db['hospital_dischargebilling'].find(query))
            
            # Preload admissions map for fallback doctor resolution
            ip_numbers = [b.get('ip_number') or b.get('ipNumber') for b in billings if (b.get('ip_number') or b.get('ipNumber'))]
            admissions_map = {}
            if ip_numbers:
                for adm in db['hospital_admission'].find({"$or": [{"ipNumber": {"$in": ip_numbers}}, {"ip_number": {"$in": ip_numbers}}]}):
                    ip_k = adm.get("ipNumber") or adm.get("ip_number")
                    if ip_k:
                        admissions_map[ip_k] = adm

            doctor_stats = {}
            for bill in billings:
                ip_num = bill.get('ip_number') or bill.get('ipNumber')
                adm = admissions_map.get(ip_num, {})
                adm_doc = adm.get('admittingDoctor') or adm.get('consultingDoctor')

                items = bill.get('items', [])
                if items:
                    for item in items:
                        doc_val = item.get('doctor') or bill.get('doctor') or bill.get('admitting_doctor') or adm_doc
                        if not doc_val: 
                            doc_val = "Hospital Service"
                        
                        doc_name_resolved = resolve_doc_name(doc_val)
                        
                        if doctor_name and doctor_name.lower() != 'all' and doc_name_resolved.lower() != doctor_name.lower():
                            continue
                            
                        if doc_name_resolved not in doctor_stats:
                            doctor_stats[doc_name_resolved] = {
                                "doctor_name": doc_name_resolved,
                                "total_collection": 0.0,
                                "bill_count": 0,
                                "patients": set()
                            }
                        
                        doctor_stats[doc_name_resolved]["total_collection"] += _safe_num(item.get('amount', 0) or item.get('rate', 0))
                        doctor_stats[doc_name_resolved]["bill_count"] += 1
                        if bill.get('uhid'):
                            doctor_stats[doc_name_resolved]["patients"].add(bill.get('uhid'))
                else:
                    doc_val = bill.get('doctor') or bill.get('admitting_doctor') or adm_doc or "Hospital Service"
                    doc_name_resolved = resolve_doc_name(doc_val)
                    if doctor_name and doctor_name.lower() != 'all' and doc_name_resolved.lower() != doctor_name.lower():
                        continue
                    if doc_name_resolved not in doctor_stats:
                        doctor_stats[doc_name_resolved] = {
                            "doctor_name": doc_name_resolved,
                            "total_collection": 0.0,
                            "bill_count": 0,
                            "patients": set()
                        }
                    doctor_stats[doc_name_resolved]["total_collection"] += _safe_num(bill.get('net_amount', 0) or bill.get('total_amount', 0))
                    doctor_stats[doc_name_resolved]["bill_count"] += 1
                    if bill.get('uhid'):
                        doctor_stats[doc_name_resolved]["patients"].add(bill.get('uhid'))
            
            for doc in doctor_stats:
                doctor_stats[doc]["patient_count"] = len(doctor_stats[doc]["patients"])
                del doctor_stats[doc]["patients"]
                results.append(doctor_stats[doc])
                
            results.sort(key=lambda x: x.get("total_collection", 0), reverse=True)

        elif report_type == 'summary':
            # Fast summary KPIs for Front Office Dashboard
            bill_q = {
                "hospital_code": {"$in": [hospital_code, None, "system"]},
                "branch_code": branch_code,
                "$or": [
                    {"billed_date": {"$gte": start_date, "$lte": end_date}},
                    {"created_date": {"$gte": start_date, "$lte": end_date}}
                ]
            }
            total_bills = db['hospital_billing'].count_documents(bill_q)

            q_pt = {
                "hospital_code": {"$in": [hospital_code, None, "system"]},
                "branch_code": branch_code,
                "$or": [
                    {"created_date": {"$gte": start_date, "$lte": end_date}},
                    {"created_date": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}},
                    {"registration_date": {"$gte": start_date_str, "$lte": end_date_str}}
                ]
            }
            total_new_pt = db['hospital_patient'].count_documents(q_pt)
            total_renew_pt = max(0, total_bills - total_new_pt)
            total_op_all = total_new_pt + total_renew_pt

            q_ref = dict(q_pt)
            q_ref["referredBy"] = {"$nin": [None, "", "null", "undefined", "-"]}
            total_ref = db['hospital_patient'].count_documents(q_ref)

            q_nb = dict(q_pt)
            q_nb["mothers_uhid_no"] = {"$nin": [None, "", "null", "undefined", "-"]}
            total_nb = db['hospital_patient'].count_documents(q_nb)

            q_adm = {
                "hospital_code": {"$in": [hospital_code, None, "system"]},
                "branch_code": branch_code,
                "$or": [
                    {"admissionDateTime": {"$gte": start_date, "$lte": end_date}},
                    {"admissionDateTime": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}}
                ]
            }
            total_adm = db['hospital_admission'].count_documents(q_adm)

            q_dis = {
                "hospital_code": {"$in": [hospital_code, None, "system"]},
                "branch_code": branch_code,
                "$or": [
                    {"bill_date": {"$gte": start_date, "$lte": end_date}},
                    {"created_date": {"$gte": start_date, "$lte": end_date}}
                ],
                "is_cancelled": {"$ne": True}
            }
            total_dis = db['hospital_dischargebilling'].count_documents(q_dis)

            dis_bills = list(db['hospital_dischargebilling'].find(q_dis, {"net_amount": 1, "total_amount": 1}))
            total_ip_rev = sum([_safe_num(b.get("net_amount") or b.get("total_amount") or 0) for b in dis_bills])

            summary_data = {
                "total_op": total_op_all,
                "total_new_op": total_new_pt,
                "total_renew_op": total_renew_pt,
                "total_referred": total_ref,
                "total_newborns": total_nb,
                "total_admissions": total_adm,
                "total_discharges": total_dis,
                "total_ip_collection": round(total_ip_rev, 2)
            }
            return Response(serialize_doc(summary_data), status=200)

        return Response(serialize_doc(results), status=200)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)
