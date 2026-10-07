from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.utils import timezone
from pyauth.auth import HasRoleAndDataPermission
from ..dbcollection import hms_db
from ...models import Admission, Patient
import traceback
import os
import csv
import re
import datetime
from bson import ObjectId, Decimal128

# MongoDB Collections
members_col = hms_db["hospital_insurancemember"]
visits_col = hms_db["hospital_insurancemembervisit"]
claims_col = hms_db["hospital_insuranceclaim"]
dependents_col = hms_db["hospital_insurancememberdependent"]

def build_date_range_filter(field_name, from_date_str, to_date_str):
    if not from_date_str and not to_date_str:
        return None

    start_dt = None
    end_dt = None

    if from_date_str:
        try:
            s_clean = str(from_date_str).split('T')[0].strip()
            d = datetime.datetime.strptime(s_clean, '%Y-%m-%d')
            start_dt = datetime.datetime(d.year, d.month, d.day, 0, 0, 0)
        except Exception:
            start_dt = None

    if to_date_str:
        try:
            s_clean = str(to_date_str).split('T')[0].strip()
            d = datetime.datetime.strptime(s_clean, '%Y-%m-%d')
            end_dt = datetime.datetime(d.year, d.month, d.day, 23, 59, 59, 999999)
        except Exception:
            end_dt = None

    conditions = []
    if start_dt and end_dt:
        conditions.append({field_name: {'$gte': start_dt, '$lte': end_dt}})
    elif start_dt:
        conditions.append({field_name: {'$gte': start_dt}})
    elif end_dt:
        conditions.append({field_name: {'$lte': end_dt}})

    f_str = str(from_date_str).split('T')[0].strip() if from_date_str else ''
    t_str = str(to_date_str).split('T')[0].strip() if to_date_str else ''

    if f_str and t_str:
        conditions.append({field_name: {'$gte': f_str, '$lte': t_str + '\uffff'}})
    elif f_str:
        conditions.append({field_name: {'$gte': f_str}})
    elif t_str:
        conditions.append({field_name: {'$lte': t_str + '\uffff'}})

    if len(conditions) == 1:
        return conditions[0]
    elif len(conditions) > 1:
        return {'$or': conditions}
    return None

def clean_mongo_doc(d):
    """
    Recursively clean and format MongoDB document types (ObjectId, Decimal128, Datetime)
    for seamless JSON serialization.
    """
    if not d:
        return None
    res = {}
    for k, v in d.items():
        if isinstance(v, ObjectId):
            res[k] = str(v)
        elif isinstance(v, Decimal128):
            res[k] = float(str(v))
        elif isinstance(v, (datetime.datetime, datetime.date)):
            res[k] = v.isoformat()
        elif isinstance(v, dict):
            res[k] = clean_mongo_doc(v)
        elif isinstance(v, list):
            res[k] = [clean_mongo_doc(x) if isinstance(x, dict) else (str(x) if isinstance(x, ObjectId) else x) for x in v]
        else:
            res[k] = v
    return res


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_patient_admission_details(request):
    """
    Fetch patient and admission details by UHID or IP Number.
    """
    uhid = request.GET.get('uhid')
    ip_number = request.GET.get('ip_number')

    from ...serializers import AdmissionSerializer
    try:
        admission = None
        if uhid:
            admission = Admission.objects.filter(uhid=uhid).order_by('-admissionDateTime').first()
        elif ip_number:
            admission = Admission.objects.filter(ipNumber=ip_number).order_by('-admissionDateTime').first()

        if not admission:
            return Response({"success": False, "error": f"Admission not found for {uhid or ip_number}"}, status=404)

        serializer = AdmissionSerializer(admission)
        return Response({"success": True, "data": serializer.data})

    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)


# ==========================================
# INSURANCE CLAIMS VIEW (NATIVE MONGO)
# ==========================================

@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def insurance_claim_view(request, claim_id=None):
    hospital_code = request.headers.get("auth-hospital-code") or "system"
    branch_code = request.headers.get("Branch-Code") or "system"
    employee_id = request.headers.get("auth-user-id") or "system"

    if request.method == 'GET':
        try:
            if claim_id:
                doc = claims_col.find_one({"claim_id": claim_id})
                if not doc:
                    return Response({"success": False, "error": "Claim not found"}, status=404)
                return Response({"success": True, "data": clean_mongo_doc(doc)})
            
            from_date = request.GET.get('from_date') or request.query_params.get('from_date')
            to_date = request.GET.get('to_date') or request.query_params.get('to_date')
            company = request.GET.get('company') or request.query_params.get('company')
            search_q = (request.GET.get('search') or request.query_params.get('search') or '').strip()
            show_deleted = (request.GET.get('show_deleted') or request.query_params.get('show_deleted')) == 'true'

            conditions = []
            if not show_deleted:
                conditions.append({"is_active": True})

            date_cond = build_date_range_filter("claim_date", from_date, to_date)
            if date_cond:
                conditions.append(date_cond)

            if company and company != 'ALL':
                conditions.append({"insurance_company": company})

            if search_q:
                rgx = re.compile(re.escape(search_q), re.IGNORECASE)
                conditions.append({"$or": [
                    {"uhid": rgx},
                    {"ip_number": rgx},
                    {"claim_id": rgx},
                    {"policy_no": rgx},
                    {"insurance_company": rgx}
                ]})

            query = {"$and": conditions} if len(conditions) > 1 else (conditions[0] if conditions else {})

            docs = list(claims_col.find(query).sort("claim_date", -1).limit(500))
            cleaned_docs = [clean_mongo_doc(d) for d in docs]

            uhids = list({d.get('uhid') for d in cleaned_docs if d.get('uhid')})
            ips = list({d.get('ip_number') for d in cleaned_docs if d.get('ip_number')})

            patient_map = {}
            if uhids:
                try:
                    for p in Patient.objects.filter(uhid__in=uhids):
                        patient_map[p.uhid] = {
                            'firstName': getattr(p, 'firstName', '') or '',
                            'lastName': getattr(p, 'lastName', '') or '',
                            'age': getattr(p, 'age', '') or '',
                            'gender': getattr(p, 'gender', '') or '',
                            'customer_type': getattr(p, 'customer_type', '') or ''
                        }
                except Exception:
                    pass

            admission_map = {}
            if ips:
                try:
                    for a in Admission.objects.filter(ipNumber__in=ips):
                        admission_map[a.ipNumber] = {
                            'admissionDateTime': a.admissionDateTime.isoformat() if getattr(a, 'admissionDateTime', None) else None,
                            'admittingDoctor': getattr(a, 'admittingDoctor', '') or '',
                            'room_details': getattr(a, 'room_details', '') or ''
                        }
                except Exception:
                    pass

            for d in cleaned_docs:
                d['patient_details'] = patient_map.get(d.get('uhid'), {})
                d['admission_details'] = admission_map.get(d.get('ip_number'), {})

            return Response({"success": True, "data": cleaned_docs})

        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'POST':
        try:
            data = request.data.copy()
            data['hospital_code'] = hospital_code
            data['branch_code'] = branch_code
            data['created_by'] = employee_id
            data['created_date'] = datetime.datetime.utcnow()
            data['is_active'] = True

            if not data.get('claim_id'):
                prefix = timezone.now().strftime('%Y%m%d')
                cnt = claims_col.count_documents({"claim_id": {"$regex": f"^CLM{prefix}"}})
                data['claim_id'] = f"CLM{prefix}{(cnt + 1):04d}"

            res = claims_col.insert_one(data)
            data['_id'] = str(res.inserted_id)
            return Response({"success": True, "message": "Claim created successfully", "data": clean_mongo_doc(data)}, status=201)
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'PATCH':
        try:
            if not claim_id:
                return Response({"success": False, "error": "Claim ID required"}, status=400)
            
            data = request.data.copy()
            data.pop('_id', None)
            data['lastmodified_by'] = employee_id
            data['lastmodified_date'] = datetime.datetime.utcnow()

            claims_col.update_one({"claim_id": claim_id}, {"$set": data})
            updated = claims_col.find_one({"claim_id": claim_id})
            return Response({"success": True, "message": "Claim updated successfully", "data": clean_mongo_doc(updated)})
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'DELETE':
        try:
            if not claim_id:
                return Response({"success": False, "error": "Claim ID required"}, status=400)
            
            claims_col.update_one(
                {"claim_id": claim_id},
                {"$set": {"is_active": False, "lastmodified_by": employee_id, "lastmodified_date": datetime.datetime.utcnow()}}
            )
            return Response({"success": True, "message": "Claim deleted successfully"})
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)


# ==========================================
# INSURANCE MEMBER MASTER VIEW (FAST NATIVE MONGO)
# ==========================================

@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def insurance_member_view(request, member_number=None):
    hospital_code = request.headers.get("auth-hospital-code") or "system"
    branch_code = request.headers.get("Branch-Code") or "system"
    employee_id = request.headers.get("auth-user-id") or "system"

    if request.method == 'GET':
        try:
            if member_number:
                doc = members_col.find_one({"member_number": member_number, "is_active": True})
                if not doc:
                    return Response({"success": False, "error": "Insurance member not found"}, status=404)
                return Response({"success": True, "data": clean_mongo_doc(doc)})

            category = request.GET.get('category') or request.query_params.get('category')
            subcategory = request.GET.get('subcategory') or request.query_params.get('subcategory')
            search_q = (request.GET.get('search') or request.query_params.get('search') or '').strip()
            search_by = request.GET.get('search_by') or request.query_params.get('search_by')
            page = max(1, int(request.GET.get('page') or request.query_params.get('page') or 1))
            limit = max(1, int(request.GET.get('limit') or request.query_params.get('limit') or 25))

            # Build query
            query = {"is_active": True}

            if category and category.upper() != 'ALL':
                query["scheme_category"] = {"$regex": f"^{re.escape(category)}$", "$options": "i"}

            if subcategory and subcategory.upper() != 'ALL':
                query["scheme_subcategory"] = {"$regex": f"^{re.escape(subcategory)}$", "$options": "i"}

            if search_q:
                rgx = re.compile(re.escape(search_q), re.IGNORECASE)
                if search_by == 'Member Name':
                    query["$or"] = [{"member_name": rgx}, {"member_first_name": rgx}]
                elif search_by == 'Member ID':
                    query["member_number"] = rgx
                elif search_by == 'UHID No':
                    query["uhid"] = rgx
                elif search_by == 'Phone':
                    query["member_phone"] = rgx
                elif search_by == 'ECHS Card':
                    query["$or"] = [{"card_no": rgx}, {"echs_card": rgx}]
                elif search_by == 'Service No':
                    query["service_number"] = rgx
                else:
                    query["$or"] = [
                        {"member_number": rgx},
                        {"member_name": rgx},
                        {"member_first_name": rgx},
                        {"uhid": rgx},
                        {"card_no": rgx},
                        {"echs_card": rgx},
                        {"member_phone": rgx},
                        {"service_number": rgx}
                    ]

            # Direct Mongo count
            total_count = members_col.count_documents(query)

            # Auto-seed once if table is empty
            if total_count == 0 and not search_q and not category:
                if members_col.count_documents({}) == 0:
                    _seed_initial_insurance_members(hospital_code, branch_code, employee_id)
                    total_count = members_col.count_documents(query)

            start_idx = (page - 1) * limit
            
            # Fast paginated slice using MongoDB native cursor
            cursor = members_col.find(query).sort("created_date", -1).skip(start_idx).limit(limit)
            paged_data = [clean_mongo_doc(d) for d in cursor]

            return Response({
                "success": True,
                "data": paged_data,
                "total_count": total_count,
                "page": page,
                "limit": limit
            })

        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'POST':
        try:
            data = request.data.copy()
            data['hospital_code'] = hospital_code
            data['branch_code'] = branch_code
            data['created_by'] = employee_id
            data['created_date'] = datetime.datetime.utcnow()
            data['is_active'] = True

            if not data.get('member_number'):
                year_prefix = timezone.now().strftime('%y')
                cnt = members_col.count_documents({"member_number": {"$regex": f"^GE{year_prefix}/"}})
                seq = cnt + 1
                data['member_number'] = f"GE{year_prefix}/{seq:05d}"

            first_name = data.get('member_first_name', '') or ''
            middle_name = data.get('member_middle_name', '') or ''
            last_name = data.get('member_last_name', '') or ''
            full_name = " ".join([p for p in [first_name, middle_name, last_name] if p]).strip()
            if full_name:
                data['member_name'] = full_name
            if not data.get('echs_card') and data.get('card_no'):
                data['echs_card'] = data['card_no']

            res = members_col.insert_one(data)
            data['_id'] = str(res.inserted_id)

            return Response({
                "success": True, 
                "message": "Insurance member created successfully", 
                "data": clean_mongo_doc(data)
            }, status=201)
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'PATCH':
        try:
            if not member_number:
                return Response({"success": False, "error": "Member number required"}, status=400)
            
            doc = members_col.find_one({"member_number": member_number})
            if not doc:
                return Response({"success": False, "error": "Insurance member not found"}, status=404)
            
            data = request.data.copy()
            data.pop('_id', None)
            data['lastmodified_by'] = employee_id
            data['lastmodified_date'] = datetime.datetime.utcnow()

            first_name = data.get('member_first_name', doc.get('member_first_name', '')) or ''
            middle_name = data.get('member_middle_name', doc.get('member_middle_name', '')) or ''
            last_name = data.get('member_last_name', doc.get('member_last_name', '')) or ''
            full_name = " ".join([p for p in [first_name, middle_name, last_name] if p]).strip()
            if full_name:
                data['member_name'] = full_name

            members_col.update_one({"member_number": member_number}, {"$set": data})
            updated = members_col.find_one({"member_number": member_number})

            return Response({
                "success": True, 
                "message": "Insurance member updated successfully", 
                "data": clean_mongo_doc(updated)
            })
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'DELETE':
        try:
            if not member_number:
                return Response({"success": False, "error": "Member number required"}, status=400)
            
            members_col.update_one(
                {"member_number": member_number},
                {"$set": {"is_active": False, "lastmodified_by": employee_id, "lastmodified_date": datetime.datetime.utcnow()}}
            )

            return Response({"success": True, "message": "Insurance member deleted successfully"})
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)


# ==========================================
# INSURANCE MEMBER DEPENDENTS (NATIVE MONGO)
# ==========================================

@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def insurance_member_dependent_view(request, member_number=None, dependent_id=None):
    hospital_code = request.headers.get("auth-hospital-code") or "system"
    branch_code = request.headers.get("Branch-Code") or "system"
    employee_id = request.headers.get("auth-user-id") or "system"

    if request.method == 'GET':
        try:
            target_member = member_number or request.GET.get('member_number')
            if not target_member:
                return Response({"success": False, "error": "member_number is required"}, status=400)
            
            docs = list(dependents_col.find({"member_number": target_member, "is_active": True}).sort("dependent_sl_no", 1))
            return Response({"success": True, "data": [clean_mongo_doc(d) for d in docs]})
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'POST':
        try:
            data = request.data.copy()
            data['hospital_code'] = hospital_code
            data['branch_code'] = branch_code
            data['created_by'] = employee_id
            data['created_date'] = datetime.datetime.utcnow()
            data['is_active'] = True

            if not data.get('member_number') and member_number:
                data['member_number'] = member_number

            cnt = dependents_col.count_documents({"member_number": data['member_number']})
            if 'dependent_sl_no' not in data or not data['dependent_sl_no']:
                data['dependent_sl_no'] = cnt + 1

            res = dependents_col.insert_one(data)
            data['_id'] = str(res.inserted_id)

            return Response({
                "success": True, 
                "message": "Dependent added successfully", 
                "data": clean_mongo_doc(data)
            }, status=201)
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'PATCH':
        try:
            dep_pk = dependent_id or request.data.get('id') or request.data.get('_id')
            if not dep_pk:
                return Response({"success": False, "error": "Dependent ID required"}, status=400)
            
            data = request.data.copy()
            data.pop('_id', None)
            data['lastmodified_by'] = employee_id
            data['lastmodified_date'] = datetime.datetime.utcnow()

            q = {"_id": ObjectId(dep_pk)} if ObjectId.is_valid(dep_pk) else {"id": dep_pk}
            dependents_col.update_one(q, {"$set": data})
            updated = dependents_col.find_one(q)

            return Response({"success": True, "message": "Dependent updated successfully", "data": clean_mongo_doc(updated)})
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'DELETE':
        try:
            dep_pk = dependent_id or request.GET.get('id') or request.GET.get('_id')
            if not dep_pk:
                return Response({"success": False, "error": "Dependent ID required"}, status=400)
            
            q = {"_id": ObjectId(dep_pk)} if ObjectId.is_valid(dep_pk) else {"id": dep_pk}
            dependents_col.update_one(q, {"$set": {"is_active": False, "lastmodified_by": employee_id, "lastmodified_date": datetime.datetime.utcnow()}})
            return Response({"success": True, "message": "Dependent deleted successfully"})
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)


# ==========================================
# INSURANCE MEMBER VISITS VIEW (FAST NATIVE MONGO)
# ==========================================

@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def insurance_member_visit_view(request, visit_ref=None):
    hospital_code = request.headers.get("auth-hospital-code") or "system"
    branch_code = request.headers.get("Branch-Code") or "system"
    employee_id = request.headers.get("auth-user-id") or "system"

    if request.method == 'GET':
        try:
            if visit_ref:
                doc = visits_col.find_one({"member_visit_reference": visit_ref, "is_active": True})
                if not doc:
                    return Response({"success": False, "error": "Visit record not found"}, status=404)
                return Response({"success": True, "data": clean_mongo_doc(doc)})

            from_date = request.GET.get('from_date') or request.query_params.get('from_date')
            to_date = request.GET.get('to_date') or request.query_params.get('to_date')
            member_number = request.GET.get('member_number') or request.query_params.get('member_number')
            search_q = (request.GET.get('search') or request.query_params.get('search') or '').strip()
            page = max(1, int(request.GET.get('page') or request.query_params.get('page') or 1))
            limit = max(1, int(request.GET.get('limit') or request.query_params.get('limit') or 10))

            conditions = [{"is_active": True}]

            date_cond = build_date_range_filter("visit_date", from_date, to_date)
            if date_cond:
                conditions.append(date_cond)

            if member_number:
                conditions.append({"member_number": {"$regex": f"^{re.escape(member_number)}$", "$options": "i"}})

            if search_q:
                rgx = re.compile(re.escape(search_q), re.IGNORECASE)
                conditions.append({"$or": [
                    {"member_visit_reference": rgx},
                    {"member_number": rgx},
                    {"patient_name": rgx},
                    {"uhid": rgx},
                    {"referral_number": rgx},
                    {"service_number": rgx},
                    {"consulting_doctor": rgx},
                    {"provisional_diagnosis": rgx}
                ]})

            query = {"$and": conditions} if len(conditions) > 1 else (conditions[0] if conditions else {})

            total_count = visits_col.count_documents(query)

            if total_count == 0 and not search_q and not member_number:
                if visits_col.count_documents({}) == 0:
                    _seed_initial_insurance_visits(hospital_code, branch_code, employee_id)
                    total_count = visits_col.count_documents(query)

            start_idx = (page - 1) * limit
            cursor = visits_col.find(query).sort([("visit_date", -1), ("visit_time", -1)]).skip(start_idx).limit(limit)
            paged_visits = [clean_mongo_doc(d) for d in cursor]

            return Response({
                "success": True,
                "data": paged_visits,
                "total_count": total_count,
                "page": page,
                "limit": limit
            })

        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'POST':
        try:
            data = request.data.copy()
            data['hospital_code'] = hospital_code
            data['branch_code'] = branch_code
            data['created_by'] = employee_id
            data['created_date'] = datetime.datetime.utcnow()
            data['is_active'] = True

            if not data.get('member_visit_reference'):
                cnt = visits_col.count_documents({})
                seq = cnt + 1
                data['member_visit_reference'] = f"{seq:06d}"

            res = visits_col.insert_one(data)
            data['_id'] = str(res.inserted_id)

            return Response({
                "success": True, 
                "message": "Member visit created successfully", 
                "data": clean_mongo_doc(data)
            }, status=201)
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'PATCH':
        try:
            if not visit_ref:
                return Response({"success": False, "error": "Visit reference required"}, status=400)
            
            data = request.data.copy()
            data.pop('_id', None)
            data['lastmodified_by'] = employee_id
            data['lastmodified_date'] = datetime.datetime.utcnow()

            visits_col.update_one({"member_visit_reference": visit_ref}, {"$set": data})
            updated = visits_col.find_one({"member_visit_reference": visit_ref})

            return Response({
                "success": True, 
                "message": "Member visit updated successfully", 
                "data": clean_mongo_doc(updated)
            })
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    elif request.method == 'DELETE':
        try:
            if not visit_ref:
                return Response({"success": False, "error": "Visit reference required"}, status=400)
            
            visits_col.update_one(
                {"member_visit_reference": visit_ref},
                {"$set": {"is_active": False, "lastmodified_by": employee_id, "lastmodified_date": datetime.datetime.utcnow()}}
            )

            return Response({"success": True, "message": "Member visit deleted successfully"})
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)


# ==========================================
# SEARCH / HELPER ENDPOINTS (FAST NATIVE MONGO)
# ==========================================

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def search_patient_details_by_uhid(request):
    """
    Lookup patient by UHID to auto-fill member or visit registration.
    """
    uhid = request.GET.get('uhid')
    if not uhid:
        return Response({"success": False, "error": "UHID is required"}, status=400)
    
    try:
        patient = Patient.objects.filter(uhid=uhid).order_by().first()
        if not patient:
            return Response({"success": False, "error": f"Patient with UHID {uhid} not found"}, status=404)
        
        return Response({
            "success": True,
            "data": {
                "uhid": patient.uhid,
                "firstName": patient.firstName,
                "lastName": patient.lastName,
                "salutation": patient.salutation,
                "gender": patient.gender,
                "dob": str(patient.dob) if patient.dob else "",
                "age": patient.age,
                "mobilePhone": patient.mobilePhone,
                "address": patient.permanent_address,
                "area": patient.area,
                "city": patient.city,
                "state": patient.state,
                "customer_type": patient.customer_type
            }
        })
    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def search_insurance_member_by_number(request):
    """
    Lookup member and active dependents by member_number, UHID, or Card No.
    """
    member_number = (request.GET.get('member_number') or '').strip()
    uhid = (request.GET.get('uhid') or '').strip()
    card_no = (request.GET.get('card_no') or '').strip()

    try:
        matched = None
        if member_number:
            matched = members_col.find_one({"member_number": {"$regex": f"^{re.escape(member_number)}$", "$options": "i"}, "is_active": True})
        elif uhid:
            matched = members_col.find_one({"uhid": {"$regex": f"^{re.escape(uhid)}$", "$options": "i"}, "is_active": True})
        elif card_no:
            rgx = re.compile(f"^{re.escape(card_no)}$", re.IGNORECASE)
            matched = members_col.find_one({"$or": [{"card_no": rgx}, {"echs_card": rgx}], "is_active": True})

        if not matched:
            return Response({"success": False, "error": "Insurance Member not found"}, status=404)

        return Response({"success": True, "data": clean_mongo_doc(matched)})
    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)


# ==========================================
# SEEDING HELPERS
# ==========================================

def _seed_initial_insurance_members(hospital_code="system", branch_code="system", employee_id="system"):
    csv_path = r"e:\SHANMUGALIVE_CSV\SHANMUGALIVE_CSV\INSURANCEMEMBERMASTER.csv"
    if os.path.exists(csv_path):
        try:
            with open(csv_path, mode='r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                header = next(reader, None)
                count = 0
                for row in reader:
                    if not row or len(row) < 5 or not row[0].strip():
                        continue
                    m_num = row[0].strip()
                    if not members_col.find_one({"member_number": m_num}):
                        first_name = row[9].strip() if len(row) > 9 else ""
                        full_name = row[12].strip() if len(row) > 12 else first_name
                        members_col.insert_one({
                            "member_number": m_num,
                            "member_first_name": first_name or full_name,
                            "member_name": full_name or first_name or m_num,
                            "hospital_code": hospital_code,
                            "branch_code": branch_code,
                            "created_by": employee_id,
                            "created_date": datetime.datetime.utcnow(),
                            "is_active": True
                        })
                        count += 1
                        if count >= 50:
                            break
        except Exception:
            pass

def _seed_initial_insurance_visits(hospital_code="system", branch_code="system", employee_id="system"):
    default_visits = [
        {"member_visit_reference": "2324/011344", "member_number": "SP26/01145", "patient_name": "S SAMUDI", "uhid": "S026/002194", "visit_date": "2026-08-06", "visit_time": "14:50:00", "opd_registration_date": "2026-08-06", "referral_number": "46802591", "service_number": "46802591", "provisional_diagnosis": "OSTEOARTHROSIS"},
        {"member_visit_reference": "2324/011345", "member_number": "GE25/06314", "patient_name": "PAPATHY", "uhid": "S024/000154", "visit_date": "2026-08-06", "visit_time": "14:51:00", "opd_registration_date": "2026-08-06", "referral_number": "01110000246587 / 46572148", "service_number": "01110000246587", "provisional_diagnosis": "ADENOCARCINOMA OF STOMACH"}
    ]
    for item in default_visits:
        item["hospital_code"] = hospital_code
        item["branch_code"] = branch_code
        item["created_by"] = employee_id
        item["created_date"] = datetime.datetime.utcnow()
        item["is_active"] = True
        visits_col.insert_one(item)
