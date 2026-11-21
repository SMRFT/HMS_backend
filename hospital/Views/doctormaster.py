import os
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from bson import Decimal128
from pymongo import MongoClient
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from pyauth.auth import HasRoleAndDataPermission

# Ensure .env is loaded from backend directory regardless of working directory
_backend_env = Path(__file__).resolve().parent.parent.parent / ".env"
if _backend_env.exists():
    load_dotenv(dotenv_path=_backend_env, override=False)
load_dotenv(override=True)

# ── Persistent Connection Pool ──────────────────────────────────────────
_client = None

def get_mongo_client():
    global _client
    if _client is None:
        host = os.getenv('GLOBAL_DB_HOST', 'mongodb://localhost:27017')
        _client = MongoClient(
            host,
            maxPoolSize=25,
            minPoolSize=2,
            connectTimeoutMS=4000,
            serverSelectionTimeoutMS=4000,
            socketTimeoutMS=8000,
            retryWrites=True
        )
    return _client


# Helper function to convert Decimal128 fields to float
def convert_decimal128_to_float(data):
    for key, value in data.items():
        if isinstance(value, Decimal128):
            data[key] = float(value.to_decimal())
        elif isinstance(value, dict):
            convert_decimal128_to_float(value)
    return data


# ── Metadata In-Memory Caches (5 min TTL) ────────────────────────────────
_dept_cache = {"data": None, "timestamp": 0}
_desig_cache = {"data": None, "timestamp": 0}
_doctor_list_cache = {"data": None, "timestamp": 0}
CACHE_TTL = 300  # 5 minutes
DOCTOR_CACHE_TTL = 120  # 2 minutes


def get_department_mapping(global_db):
    now = time.time()
    if _dept_cache["data"] is not None and (now - _dept_cache["timestamp"] < CACHE_TTL):
        return _dept_cache["data"]
    try:
        dept_collection = global_db['backend_diagnostics_Departments']
        dept_mapping = {}
        for d in dept_collection.find({}, {"department_code": 1, "dept_code": 1, "code": 1, "department_name": 1, "dept_name": 1, "name": 1, "_id": 0}):
            code = d.get('department_code') or d.get('dept_code') or d.get('code')
            name = d.get('department_name') or d.get('dept_name') or d.get('name')
            if code and name:
                dept_mapping[code] = name
        _dept_cache["data"] = dept_mapping
        _dept_cache["timestamp"] = now
        return dept_mapping
    except Exception as e:
        print("Error fetching department mapping:", e)
        if _dept_cache["data"] is not None:
            return _dept_cache["data"]
        return {}


def get_designation_mapping(global_db):
    now = time.time()
    if _desig_cache["data"] is not None and (now - _desig_cache["timestamp"] < CACHE_TTL):
        return _desig_cache["data"]
    try:
        desig_collection = global_db['backend_diagnostics_Designation']
        desig_mapping = {}
        for d in desig_collection.find({}, {"Designation_code": 1, "designation_code": 1, "code": 1, "designation": 1, "designation_name": 1, "name": 1, "_id": 0}):
            code = d.get('Designation_code') or d.get('designation_code') or d.get('code')
            name = d.get('designation') or d.get('designation_name') or d.get('name')
            if code and name:
                desig_mapping[code] = name
        _desig_cache["data"] = desig_mapping
        _desig_cache["timestamp"] = now
        return desig_mapping
    except Exception as e:
        print("Error fetching designation mapping:", e)
        if _desig_cache["data"] is not None:
            return _desig_cache["data"]
        return {}


def get_active_doctor_profiles(global_db, projection):
    """
    Return de-duplicated doctor profiles that satisfy BOTH:
      1. backend_diagnostics_profile.isDoctor == True
      2. backend_diagnostics_user.is_active == True (matched by employeeId)
    No other filters (designation / role / name pattern) are applied.
    """
    profile_collection = global_db['backend_diagnostics_profile']
    user_collection = global_db['backend_diagnostics_user']

    # Make sure employeeId is always projected (needed for dedupe + active check)
    proj = dict(projection)
    proj["employeeId"] = 1
    proj["_id"] = 0

    profiles = list(profile_collection.find({"isDoctor": True}, proj))

    # Deduplicate by employeeId
    unique_profiles = []
    seen_emp_ids = set()
    for doc in profiles:
        eid = str(doc.get("employeeId") or "").strip()
        if not eid or eid in seen_emp_ids:
            continue
        seen_emp_ids.add(eid)
        unique_profiles.append(doc)

    if not unique_profiles:
        return []

    # Fetch all active user employee IDs directly (collection has no index on employeeId,
    # so simple find({"is_active": True}) is sub-second, whereas unindexed $in hangs).
    active_users = user_collection.find(
        {"is_active": True},
        {"employeeId": 1, "_id": 0}
    )
    active_emp_ids = {str(u.get("employeeId") or "").strip() for u in active_users if u.get("employeeId")}

    return [
        doc for doc in unique_profiles
        if str(doc.get("employeeId") or "").strip() in active_emp_ids
    ]


@api_view(['GET'])
@permission_classes([AllowAny])
def doctor_list_from_diagnostics(request):
    """Get list of doctors (isDoctor=True in profile AND is_active=True in user) with resolved Department and Designation names"""
    now = time.time()
    # Fast path: serve from in-memory cache (<1ms response time)
    if _doctor_list_cache["data"] is not None and (now - _doctor_list_cache["timestamp"] < DOCTOR_CACHE_TTL):
        return Response(_doctor_list_cache["data"], status=status.HTTP_200_OK)

    try:
        client = get_mongo_client()
        global_db = client['Global']

        # Get Mappings
        dept_map = get_department_mapping(global_db)
        desig_map = get_designation_mapping(global_db)

        doctors = get_active_doctor_profiles(
            global_db,
            {
                "employeeName": 1,
                "department": 1,
                "specialty": 1,
                "designation": 1,
                "registrationNumber": 1,
            }
        )

        # Map codes to human readable names
        result = []
        for doc in doctors:
            raw_dept = doc.get("department")
            doc["department"] = dept_map.get(raw_dept, raw_dept) if raw_dept else "N/A"

            raw_desig = doc.get("designation")
            doc["designation"] = desig_map.get(raw_desig, raw_desig) if raw_desig else "Doctor"

            raw_reg = doc.get("registrationNumber")
            doc["registrationNumber"] = str(raw_reg).strip() if raw_reg else ""
            result.append(doc)

        _doctor_list_cache["data"] = result
        _doctor_list_cache["timestamp"] = now
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        # Fallback to stale cache if available, preventing 500 error during transient network drops
        if _doctor_list_cache["data"] is not None:
            return Response(_doctor_list_cache["data"], status=status.HTTP_200_OK)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def doctor_schedule_list(request):
    """Get list of doctors (isDoctor=True in profile AND is_active=True in user) with schedule details and resolved Department & Designation names"""
    try:
        client = get_mongo_client()
        global_db = client['Global']

        # Get Mappings
        dept_map = get_department_mapping(global_db)
        desig_map = get_designation_mapping(global_db)

        doctors = get_active_doctor_profiles(
            global_db,
            {
                "employeeName": 1,
                "department": 1,
                "specialty": 1,
                "designation": 1,
                "email": 1,
                "mobileNumber": 1,
            }
        )

        # Get schedules for these doctors
        hms_db = client['HMS']
        doctor_collection = hms_db['hospital_doctor']

        # Batch fetch all schedules in a single query to eliminate N+1 network latency
        emp_ids = [doc.get('employeeId') for doc in doctors if doc.get('employeeId')]
        schedules_map = {
            s.get("employeeId"): s
            for s in doctor_collection.find({"employeeId": {"$in": emp_ids}})
        }

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
                "insurance_consulting_fee": 0,
                "review_fee": 0,
                "registration_fee": 0,
                "day_schedule": [],
                "time_schedule": [],
                "schedule_exists": False
            }

            schedule = schedules_map.get(employee_id)
            if schedule:
                doc_data.update({
                    "consulting_fee": schedule.get("consulting_fee", 0),
                    "insurance_consulting_fee": schedule.get("insurance_consulting_fee", 0),
                    "review_fee": schedule.get("review_fee", 0),
                    "registration_fee": schedule.get("registration_fee", 0),
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
        client = get_mongo_client()
        global_db = client['Global']
        user_collection = global_db['backend_diagnostics_user']

        # Verify doctor is active in backend_diagnostics_user
        emp_id_str = str(employee_id).strip()
        user_filter = [emp_id_str]
        if emp_id_str.isdigit():
            user_filter.append(int(emp_id_str))

        active_user = user_collection.find_one(
            {"employeeId": {"$in": user_filter}, "is_active": True}
        )
        if not active_user:
            return Response(
                {"error": "Doctor account is inactive or not found in user master"},
                status=status.HTTP_404_NOT_FOUND
            )

        diagnostics_collection = global_db['backend_diagnostics_profile']
        diagnostic_profile = diagnostics_collection.find_one(
            {"employeeId": employee_id}
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

        raw_dept = diagnostic_profile.get("department")
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
            "insurance_consulting_fee": "",
            "review_fee": "",
            "registration_fee": "",
            "day_schedule": [],
            "time_schedule": []
        }

        if doctor_schedule:
            response_data.update({
                "consulting_fee": doctor_schedule.get("consulting_fee", ""),
                "insurance_consulting_fee": doctor_schedule.get("insurance_consulting_fee", ""),
                "review_fee": doctor_schedule.get("review_fee", ""),
                "registration_fee": doctor_schedule.get("registration_fee", ""),
                "day_schedule": doctor_schedule.get("day_schedule", []),
                "time_schedule": doctor_schedule.get("time_schedule", [])
            })
            response_data["schedule_exists"] = True
        else:
            response_data["schedule_exists"] = False

        response_data = convert_decimal128_to_float(response_data)
        _doctor_list_cache["timestamp"] = 0  # Invalidate cache
        return Response(response_data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST', 'PATCH'])
@permission_classes([HasRoleAndDataPermission])
def doctor_schedule_upsert(request, employee_id):
    """Create or update doctor schedule by employeeId"""
    try:
        client = get_mongo_client()
        branch_code = request.data.get("auth-branch-code", "system")
        hospital_code = request.data.get("auth-hospital-code", "system")

        global_db = client['Global']
        user_collection = global_db['backend_diagnostics_user']

        # Verify doctor is active in backend_diagnostics_user
        emp_id_str = str(employee_id).strip()
        user_filter = [emp_id_str]
        if emp_id_str.isdigit():
            user_filter.append(int(emp_id_str))

        active_user = user_collection.find_one(
            {"employeeId": {"$in": user_filter}, "is_active": True}
        )
        if not active_user:
            return Response(
                {"error": "Cannot update schedule: doctor account is inactive or not found in user master"},
                status=status.HTTP_400_BAD_REQUEST
            )

        diagnostics_collection = global_db['backend_diagnostics_profile']
        diagnostic_profile = diagnostics_collection.find_one(
            {"employeeId": employee_id}
        )

        if not diagnostic_profile:
            return Response(
                {"error": "Doctor not found in diagnostics profile"},
                status=status.HTTP_404_NOT_FOUND
            )
        created_by = request.data.get('auth-user-id', "system")

        schedule_data = {
            "employeeId": employee_id,
            "consulting_fee": request.data.get("consulting_fee", ""),
            "insurance_consulting_fee": request.data.get("insurance_consulting_fee", ""),
            "review_fee": request.data.get("review_fee", ""),
            "registration_fee": request.data.get("registration_fee", ""),
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
                {
                    "$set": schedule_data,
                    "$unset": {"department": ""}
                }
            )
            message = "Doctor schedule updated successfully"
        else:
            doctor_collection.insert_one(schedule_data)
            message = "Doctor schedule created successfully"

        updated_schedule = doctor_collection.find_one({"employeeId": employee_id})
        response_data = {key: updated_schedule[key] for key in updated_schedule if key != '_id'}
        response_data = convert_decimal128_to_float(response_data)
        response_data["message"] = message

        _doctor_list_cache["timestamp"] = 0  # Invalidate cache
        return Response(response_data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)