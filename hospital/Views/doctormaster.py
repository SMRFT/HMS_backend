from bson import Decimal128
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission

# Helper function to convert Decimal128 fields to float
def convert_decimal128_to_float(data):
    for key, value in data.items():
        if isinstance(value, Decimal128):
            data[key] = float(value.to_decimal())
        elif isinstance(value, dict):
            convert_decimal128_to_float(value)
    return data

# Helper function to build department code -> name mapping from backend_diagnostics_Departments
def get_department_mapping(global_db):
    try:
        dept_collection = global_db['backend_diagnostics_Departments']
        dept_mapping = {}
        for d in dept_collection.find({}):
            code = d.get('department_code') or d.get('dept_code') or d.get('code')
            name = d.get('department_name') or d.get('dept_name') or d.get('name')
            if code and name:
                dept_mapping[code] = name
        return dept_mapping
    except Exception as e:
        print("Error fetching department mapping:", e)
        return {}

# Helper function to build designation code -> name mapping from backend_diagnostics_Designation
def get_designation_mapping(global_db):
    try:
        desig_collection = global_db['backend_diagnostics_Designation']
        desig_mapping = {}
        for d in desig_collection.find({}):
            code = d.get('Designation_code') or d.get('designation_code') or d.get('code')
            name = d.get('designation') or d.get('designation_name') or d.get('name')
            if code and name:
                desig_mapping[code] = name
        return desig_mapping
    except Exception as e:
        print("Error fetching designation mapping:", e)
        return {}


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def doctor_list_from_diagnostics(request):
    """Get list of doctors from backend_diagnostics_profile with resolved Department and Designation names"""
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        global_db = client['Global']
        diagnostics_collection = global_db['backend_diagnostics_profile']
        
        # Get Mappings
        dept_map = get_department_mapping(global_db)
        desig_map = get_designation_mapping(global_db)

        # Find all profiles with DESIG094 designation
        doctors = list(diagnostics_collection.find(
            {"designation": "DESIG094"},
            {"employeeId": 1, "employeeName": 1, "department": 1, "specialty": 1, "designation": 1, "_id": 0}
        ))
        
        # Map codes to human readable names
        for doc in doctors:
            raw_dept = doc.get("department")
            doc["department"] = dept_map.get(raw_dept, raw_dept) if raw_dept else "N/A"

            raw_desig = doc.get("designation")
            doc["designation"] = desig_map.get(raw_desig, raw_desig) if raw_desig else "Doctor"
        
        return Response(doctors, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def doctor_schedule_list(request):
    """Get list of all doctors with schedule details and resolved Department & Designation names"""
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        global_db = client['Global']
        diagnostics_collection = global_db['backend_diagnostics_profile']
        
        # Get Mappings
        dept_map = get_department_mapping(global_db)
        desig_map = get_designation_mapping(global_db)

        doctors_cursor = diagnostics_collection.find(
            {"designation": "DESIG094"},
            {"employeeId": 1, "employeeName": 1, "department": 1, "specialty": 1, "designation": 1, "email": 1, "mobileNumber": 1, "_id": 0} 
        )
        doctors = list(doctors_cursor)
        
        # Get schedules for these doctors
        hms_db = client['HMS']
        doctor_collection = hms_db['hospital_doctor']
        
        detailed_doctors = []
        for doc in doctors:
            employee_id = doc.get('employeeId')
            
            emp_name = doc.get('employeeName', '')
            name_parts = emp_name.split(' ')
            first_name = name_parts[0] if name_parts else ''
            last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
            
            raw_dept = doc.get('department')
            resolved_dept = dept_map.get(raw_dept, raw_dept) if raw_dept else "N/A"

            raw_desig = doc.get('designation')
            resolved_desig = desig_map.get(raw_desig, raw_desig) if raw_desig else "Doctor"

            doc_data = {
                "employeeId": employee_id,
                "first_name": first_name,
                "middle_name": "",
                "last_name": last_name,
                "employeeName": emp_name,
                "department": resolved_dept,
                "designation": resolved_desig,
                "email": doc.get('email', ''),
                "mobileNumber": doc.get('mobileNumber', ''),
                "specialty": doc.get('specialty', 'General'),
                "consulting_fee": 0,
                "registration_fee": 0, 
                "renewal_fee": 0,
                "day_schedule": [],
                "time_schedule": [],
                "schedule_exists": False
            }
            
            schedule = doctor_collection.find_one({"employeeId": employee_id})
            if schedule:
                sch_dept = schedule.get("department")
                if sch_dept:
                    doc_data["department"] = dept_map.get(sch_dept, sch_dept)

                doc_data.update({
                    "consulting_fee": schedule.get("consulting_fee", 0),
                    "renewal_fee": schedule.get("renewal_fee", 0),
                    "registration_fee": schedule.get("renewal_fee", 0),
                    "day_schedule": schedule.get("day_schedule", []),
                    "time_schedule": schedule.get("time_schedule", []),
                    "schedule_exists": True
                })
                
            convert_decimal128_to_float(doc_data)
            detailed_doctors.append(doc_data)
            
        return Response(detailed_doctors, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def doctor_schedule_detail(request, employee_id):
    """Get doctor schedule details by employeeId with resolved Department and Designation names"""
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        global_db = client['Global']
        diagnostics_collection = global_db['backend_diagnostics_profile']
        diagnostic_profile = diagnostics_collection.find_one(
            {"employeeId": employee_id, "designation": "DESIG094"}
        )
        
        if not diagnostic_profile:
            return Response(
                {"error": "Doctor not found in diagnostics profile"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get Mappings
        dept_map = get_department_mapping(global_db)
        desig_map = get_designation_mapping(global_db)

        # Get from hospital_doctor if exists
        hms_db = client['HMS']
        doctor_collection = hms_db['hospital_doctor']
        doctor_schedule = doctor_collection.find_one({"employeeId": employee_id})
        
        raw_dept = (doctor_schedule.get("department") if doctor_schedule else None) or diagnostic_profile.get("department")
        resolved_dept = dept_map.get(raw_dept, raw_dept) if raw_dept else ""

        raw_desig = diagnostic_profile.get("designation")
        resolved_desig = desig_map.get(raw_desig, raw_desig) if raw_desig else "Doctor"

        response_data = {
            "employeeId": diagnostic_profile.get("employeeId"),
            "employeeName": diagnostic_profile.get("employeeName"),
            "email": diagnostic_profile.get("email"),
            "mobileNumber": diagnostic_profile.get("mobileNumber"),
            "department": resolved_dept,
            "designation": resolved_desig,
            "consulting_fee": "",
            "renewal_fee": "",
            "day_schedule": [],
            "time_schedule": []
        }
        
        if doctor_schedule:
            response_data.update({
                "consulting_fee": doctor_schedule.get("consulting_fee", ""),
                "renewal_fee": doctor_schedule.get("renewal_fee", ""),
                "day_schedule": doctor_schedule.get("day_schedule", []),
                "time_schedule": doctor_schedule.get("time_schedule", [])
            })
            response_data["schedule_exists"] = True
        else:
            response_data["schedule_exists"] = False
        
        response_data = convert_decimal128_to_float(response_data)
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST', 'PATCH'])
@permission_classes([HasRoleAndDataPermission])
def doctor_schedule_upsert(request, employee_id):
    """Create or update doctor schedule by employeeId"""
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        branch_code   = request.data.get("auth-branch-code",   "system")
        hospital_code = request.data.get("auth-hospital-code", "system")
        
        global_db = client['Global']
        diagnostics_collection = global_db['backend_diagnostics_profile']
        diagnostic_profile = diagnostics_collection.find_one(
            {"employeeId": employee_id, "designation": "DESIG094"}
        )
        
        if not diagnostic_profile:
            return Response(
                {"error": "Doctor not found in diagnostics profile"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        created_by = request.data.get('auth-user-id', "system")
        
        schedule_data = {
            "employeeId": employee_id,
            "department": request.data.get("department", diagnostic_profile.get("department", "")),
            "consulting_fee": request.data.get("consulting_fee", ""),
            "renewal_fee": request.data.get("renewal_fee", ""),
            "day_schedule": request.data.get("day_schedule", []),
            "time_schedule": request.data.get("time_schedule", []),
            "created_by": created_by,
            "created_date": datetime.utcnow(),
            "hospital_code": hospital_code,
            "branch_code": branch_code
        }
        
        hms_db = client['HMS']
        doctor_collection = hms_db['hospital_doctor']
        existing_schedule = doctor_collection.find_one({"employeeId": employee_id})
        
        if existing_schedule:
            result = doctor_collection.update_one(
                {"employeeId": employee_id},
                {"$set": schedule_data}
            )
            message = "Doctor schedule updated successfully"
        else:
            doctor_collection.insert_one(schedule_data)
            message = "Doctor schedule created successfully"
        
        updated_schedule = doctor_collection.find_one({"employeeId": employee_id})
        response_data = {key: updated_schedule[key] for key in updated_schedule if key != '_id'}
        response_data = convert_decimal128_to_float(response_data)
        response_data["message"] = message
        
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
