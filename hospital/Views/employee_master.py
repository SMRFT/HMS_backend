import os
import re
from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from pyauth.auth import HasRoleAndDataPermission
from .dbcollection import global_db, hms_db, profile_collection, user_collection

def serialize_date(d):
    if not d:
        return ""
    if isinstance(d, datetime):
        return d.strftime('%Y-%m-%d')
    if isinstance(d, str):
        # if ISO or other string, return first 10 chars if YYYY-MM-DD
        if len(d) >= 10 and re.match(r'^\d{4}-\d{2}-\d{2}', d):
            return d[:10]
        return d
    return str(d)

def parse_date(date_str):
    if not date_str:
        return None
    try:
        # Expected YYYY-MM-DD
        return datetime.strptime(str(date_str)[:10], '%Y-%m-%d')
    except Exception:
        return str(date_str)

def get_active_user_employee_ids():
    """
    Fetch all employeeIds from backend_diagnostics_user where is_active is True.
    """
    return {
        str(doc.get('employeeId')).strip()
        for doc in user_collection.find({'is_active': True}, {'employeeId': 1})
        if doc.get('employeeId')
    }

def is_employee_active(emp, active_user_ids=None):
    """
    Check if employee is active by comparing is_active = True in backend_diagnostics_user.
    """
    if active_user_ids is None:
        active_user_ids = get_active_user_employee_ids()
    emp_id = str(emp.get('employeeId') or emp.get('_id') or '').strip()
    return emp_id in active_user_ids

def get_mappings():
    """Retrieve departments, designations, cash counters, and doctors."""
    dept_col = global_db['backend_diagnostics_Departments']
    desig_col = global_db['backend_diagnostics_Designation']
    cashcounter_col = hms_db['hospital_cashcounter']
    doctor_col = hms_db['hospital_doctor']

    departments = []
    dept_map = {}
    for d in dept_col.find({"is_active": {"$ne": False}}, {"department_code": 1, "department_id": 1, "department_name": 1, "_id": 0}):
        code = str(d.get('department_code') or d.get('department_id') or '').strip()
        name = str(d.get('department_name') or '').strip()
        if code and name:
            dept_map[code] = name
            departments.append({"code": code, "name": name})
    departments.sort(key=lambda x: x["name"].lower())

    designations = []
    desig_map = {}
    for d in desig_col.find({"is_active": {"$ne": False}}, {"Designation_code": 1, "designation_code": 1, "designation_id": 1, "designation": 1, "designation_name": 1, "_id": 0}):
        code = str(d.get('Designation_code') or d.get('designation_code') or d.get('designation_id') or '').strip()
        name = str(d.get('designation') or d.get('designation_name') or '').strip()
        if code and name:
            desig_map[code] = name
            designations.append({"code": code, "name": name})
    designations.sort(key=lambda x: x["name"].lower())

    cashcounters = []
    counter_map = {}
    for c in cashcounter_col.find({"is_active": {"$ne": False}}, {"counter_id": 1, "counter_name": 1, "_id": 0}):
        cid = str(c.get('counter_id') or '').strip()
        cname = str(c.get('counter_name') or '').strip()
        if cid and cname:
            counter_map[cid] = cname
            cashcounters.append({"counter_id": cid, "counter_name": cname})
    cashcounters.sort(key=lambda x: x["counter_name"].lower())

    # Doctors list from hospital_doctor & profiles
    doctor_ids = set()
    for doc in doctor_col.find({}, {"employeeId": 1, "_id": 0}):
        did = str(doc.get('employeeId') or '').strip()
        if did:
            doctor_ids.add(did)

    active_user_ids = get_active_user_employee_ids()

    doctors = []
    for emp in profile_collection.find(
        {"$or": [
            {"employeeId": {"$in": list(doctor_ids)}},
            {"isDoctor": True},
            {"employeeName": {"$regex": r"^\s*dr\b", "$options": "i"}}
        ]},
        {"employeeId": 1, "employeeName": 1, "department": 1, "_id": 0}
    ):
        if not is_employee_active(emp, active_user_ids):
            continue
        eid = str(emp.get('employeeId') or '').strip()
        ename = str(emp.get('employeeName') or '').strip()
        if eid and ename:
            doctors.append({"employeeId": eid, "employeeName": ename})
    doctors.sort(key=lambda x: x["employeeName"].lower())

    return departments, dept_map, designations, desig_map, cashcounters, counter_map, doctor_ids, doctors

def format_employee_record(emp, dept_map, desig_map, counter_map, doctor_ids):
    emp_id = str(emp.get('employeeId') or emp.get('_id') or '').strip()
    emp_name = str(emp.get('employeeName') or '').strip()
    
    # Split names if separate fields don't exist
    first_name = emp.get('firstName')
    middle_name = emp.get('middleName')
    last_name = emp.get('lastName')
    if not first_name and emp_name:
        parts = emp_name.split()
        first_name = parts[0] if len(parts) > 0 else ""
        if len(parts) == 2:
            last_name = parts[1]
            middle_name = ""
        elif len(parts) > 2:
            middle_name = " ".join(parts[1:-1])
            last_name = parts[-1]
        else:
            middle_name = ""
            last_name = ""

    dept_code = str(emp.get('department') or '').strip()
    desig_code = str(emp.get('designation') or '').strip()
    dept_name = dept_map.get(dept_code, dept_code)
    desig_name = desig_map.get(desig_code, desig_code)

    additional_roles = emp.get('additionalRoles') or []
    has_hms = 'HMS-R-V' in additional_roles

    cid = str(emp.get('cashcounter') or emp.get('assigned_counter') or '').strip()
    cname = emp.get('assigned_counter_name') or counter_map.get(cid, cid)

    # Doctor flag
    is_doctor = (
        emp_id in doctor_ids or
        emp.get('isDoctor') is True or
        'doctor' in desig_name.lower() or
        emp_name.strip().lower().startswith('dr')
    )

    # Qualifications
    quals = emp.get('qualifications') or []
    q1 = emp.get('qualification1') or (quals[0].get('degree') if len(quals) > 0 and isinstance(quals[0], dict) else "")
    q2 = emp.get('qualification2') or (quals[1].get('degree') if len(quals) > 1 and isinstance(quals[1], dict) else "")

    return {
        "employeeId": emp_id,
        "employeeName": emp_name,
        "firstName": first_name or "",
        "middleName": middle_name or "",
        "lastName": last_name or "",
        "guardian": emp.get('guardian') or emp.get('fatherName') or "",
        "fatherName": emp.get('fatherName') or "",
        "motherName": emp.get('motherName') or "",
        "gender": (emp.get('gender') or "").capitalize(),
        "maritalStatus": (emp.get('maritalStatus') or "").capitalize(),
        "spouseName": emp.get('spouseName') or "",
        "dateOfBirth": serialize_date(emp.get('dateOfBirth')),
        "age": emp.get('age') or "",
        "addressLine1": emp.get('addressLine1') or emp.get('address') or "",
        "addressLine2": emp.get('addressLine2') or "",
        "addressLine3": emp.get('addressLine3') or "",
        "area": emp.get('area') or "",
        "mobileNumber": emp.get('mobileNumber') or emp.get('phone') or "",
        "email": emp.get('email') or "",
        "dateOfJoining": serialize_date(emp.get('dateOfJoining') or emp.get('doj') or emp.get('joiningDate')),
        "permanentDate": serialize_date(emp.get('permanentDate')),
        "category": emp.get('category') or "General",
        "department": dept_code,
        "department_name": dept_name,
        "designation": desig_code,
        "designation_name": desig_name,
        "has_hms": has_hms,
        "additionalRoles": additional_roles,
        "primaryRole": emp.get('primaryRole') or "",
        "cashcounter": cid,
        "cashcounter_name": cname,
        "isDoctor": is_doctor,
        "doctorAssistant": bool(emp.get('doctorAssistant')),
        "consultant": bool(emp.get('consultant')),
        "doctors": emp.get('doctors') or [],
        "qualification1": q1 or "",
        "qualification2": q2 or "",
        "profileImage": emp.get('profileImage'),
        "signatureFileId": emp.get('signatureFileId'),
        "kycDetails": emp.get('kycDetails') or {},
        "bankDetails": emp.get('bankDetails') or {},
        "familyDetails": emp.get('familyDetails') or {},
    }

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def employee_master_list(request):
    """
    GET /_b_a_c_k_e_n_d/HMS/employee-master/
    Query Params:
      search: search string for employeeId or employeeName
      is_doctor: true/false filter
      page: integer (default 1)
      limit: integer (default 20, 0 for all)
      include_dropdowns: true/false
    """
    try:
        departments, dept_map, designations, desig_map, cashcounters, counter_map, doctor_ids, doctors = get_mappings()

        search = (request.query_params.get('search') or '').strip()
        is_doctor_param = request.query_params.get('is_doctor')
        page = int(request.query_params.get('page', 1))
        limit = int(request.query_params.get('limit', 20))

        # Query builder for backend_diagnostics_profile
        match_query = {}
        if search:
            match_query["$or"] = [
                {"employeeId": {"$regex": search, "$options": "i"}},
                {"employeeName": {"$regex": search, "$options": "i"}},
                {"mobileNumber": {"$regex": search, "$options": "i"}},
            ]

        # Fetch records
        cursor = profile_collection.find(match_query).sort("employeeId", 1)
        all_records = list(cursor)

        active_user_ids = get_active_user_employee_ids()

        formatted_list = []
        for emp in all_records:
            # Only get active employees where is_active is True in backend_diagnostics_user
            if not is_employee_active(emp, active_user_ids):
                continue
            rec = format_employee_record(emp, dept_map, desig_map, counter_map, doctor_ids)
            if is_doctor_param is not None and is_doctor_param.lower() in ['true', '1', 'yes']:
                if not rec['isDoctor']:
                    continue
            formatted_list.append(rec)

        total = len(formatted_list)
        if limit > 0:
            start = (page - 1) * limit
            end = start + limit
            paginated_list = formatted_list[start:end]
        else:
            paginated_list = formatted_list

        total_pages = (total + limit - 1) // limit if limit > 0 else 1

        return Response({
            "success": True,
            "data": {
                "employees": paginated_list,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total,
                    "total_pages": total_pages,
                },
                "departments": departments,
                "designations": designations,
                "cashcounters": cashcounters,
                "doctors": doctors,
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(['GET', 'POST', 'PATCH'])
@permission_classes([HasRoleAndDataPermission])
def employee_master_detail(request, employee_id):
    """
    GET/POST/PATCH /_b_a_c_k_e_n_d/HMS/employee-master/<employee_id>/
    Update employee in backend_diagnostics_profile.
    """
    if not employee_id:
        return Response({"success": False, "message": "Employee ID is required"}, status=400)

    try:
        departments, dept_map, designations, desig_map, cashcounters, counter_map, doctor_ids, doctors = get_mappings()

        emp = profile_collection.find_one({"employeeId": str(employee_id)})
        if not emp:
            # Try numeric if integer
            emp = profile_collection.find_one({"_id": str(employee_id)})
            if not emp:
                return Response({"success": False, "message": f"Employee {employee_id} not found"}, status=404)

        if request.method == 'GET':
            rec = format_employee_record(emp, dept_map, desig_map, counter_map, doctor_ids)
            return Response({"success": True, "data": rec})

        # PATCH / POST update
        data = request.data or {}
        user_id = request.data.get("auth-user-id") or request.META.get("HTTP_AUTH_USER_ID", "system")

        set_fields = {
            "lastmodified_by": user_id,
            "lastmodified_date": datetime.utcnow()
        }
        push_fields = {}
        pull_fields = {}

        # 1. HMS Toggle -> modifies additionalRoles
        if "has_hms" in data:
            has_hms = bool(data.get("has_hms"))
            current_roles = list(emp.get("additionalRoles") or [])
            if has_hms:
                if "HMS-R-V" not in current_roles:
                    current_roles.append("HMS-R-V")
            else:
                current_roles = [r for r in current_roles if r != "HMS-R-V"]
            set_fields["additionalRoles"] = current_roles

        # 2. Cash Counter
        if "cashcounter" in data or "assigned_counter" in data:
            cid = str(data.get("cashcounter") or data.get("assigned_counter") or "").strip()
            cname = counter_map.get(cid, "")
            set_fields["cashcounter"] = cid
            set_fields["assigned_counter"] = cid
            set_fields["assigned_counter_name"] = cname

        # 3. Demographics
        first_name = (data.get("firstName") or "").strip()
        middle_name = (data.get("middleName") or "").strip()
        last_name = (data.get("lastName") or "").strip()
        
        # Determine employeeName
        if first_name or last_name:
            name_parts = [p for p in [first_name, middle_name, last_name] if p]
            set_fields["employeeName"] = " ".join(name_parts)
            set_fields["firstName"] = first_name
            set_fields["middleName"] = middle_name
            set_fields["lastName"] = last_name
        elif "employeeName" in data and data["employeeName"]:
            set_fields["employeeName"] = data["employeeName"].strip()

        if "guardian" in data:
            set_fields["guardian"] = data["guardian"].strip()
            set_fields["fatherName"] = data["guardian"].strip()
        elif "fatherName" in data:
            set_fields["fatherName"] = data["fatherName"].strip()

        if "gender" in data:
            set_fields["gender"] = str(data["gender"]).lower()
        if "maritalStatus" in data:
            set_fields["maritalStatus"] = str(data["maritalStatus"]).lower()
        if "spouseName" in data:
            set_fields["spouseName"] = data["spouseName"]
        if "dateOfBirth" in data:
            set_fields["dateOfBirth"] = parse_date(data["dateOfBirth"])
        if "age" in data and data["age"] is not None:
            try:
                set_fields["age"] = int(data["age"])
            except Exception:
                set_fields["age"] = data["age"]

        if "addressLine1" in data:
            set_fields["addressLine1"] = data["addressLine1"]
            set_fields["address"] = data["addressLine1"]
        if "addressLine2" in data:
            set_fields["addressLine2"] = data["addressLine2"]
        if "addressLine3" in data:
            set_fields["addressLine3"] = data["addressLine3"]
        if "area" in data:
            set_fields["area"] = data["area"]
        if "mobileNumber" in data:
            set_fields["mobileNumber"] = data["mobileNumber"]
            set_fields["phone"] = data["mobileNumber"]
        if "email" in data:
            set_fields["email"] = data["email"]

        if "dateOfJoining" in data:
            set_fields["dateOfJoining"] = parse_date(data["dateOfJoining"])
            set_fields["doj"] = set_fields["dateOfJoining"]
        if "permanentDate" in data:
            set_fields["permanentDate"] = parse_date(data["permanentDate"])
        if "category" in data:
            set_fields["category"] = data["category"]

        if "department" in data:
            set_fields["department"] = data["department"]
        if "designation" in data:
            set_fields["designation"] = data["designation"]

        if "doctorAssistant" in data:
            set_fields["doctorAssistant"] = bool(data["doctorAssistant"])
        if "consultant" in data:
            set_fields["consultant"] = bool(data["consultant"])
        if "doctors" in data:
            set_fields["doctors"] = data["doctors"]

        if "qualification1" in data:
            set_fields["qualification1"] = data["qualification1"]
        if "qualification2" in data:
            set_fields["qualification2"] = data["qualification2"]

        if "profileImage" in data:
            set_fields["profileImage"] = data["profileImage"]
        if "signatureFileId" in data:
            set_fields["signatureFileId"] = data["signatureFileId"]

        # Optional tab details
        if "kycDetails" in data and isinstance(data["kycDetails"], dict):
            current_kyc = emp.get("kycDetails") or {}
            current_kyc.update(data["kycDetails"])
            set_fields["kycDetails"] = current_kyc

        if "bankDetails" in data and isinstance(data["bankDetails"], dict):
            current_bank = emp.get("bankDetails") or {}
            current_bank.update(data["bankDetails"])
            set_fields["bankDetails"] = current_bank

        if "familyDetails" in data and isinstance(data["familyDetails"], dict):
            current_family = emp.get("familyDetails") or {}
            current_family.update(data["familyDetails"])
            set_fields["familyDetails"] = current_family

        update_doc = {"$set": set_fields}
        profile_collection.update_one({"employeeId": str(employee_id)}, update_doc)

        # Re-fetch updated
        updated_emp = profile_collection.find_one({"employeeId": str(employee_id)})
        rec = format_employee_record(updated_emp, dept_map, desig_map, counter_map, doctor_ids)

        return Response({
            "success": True,
            "message": "Employee updated successfully",
            "data": rec
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)

