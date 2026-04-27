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


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def doctor_list_from_diagnostics(request):
    """Get list of doctors from backend_diagnostics_profile where designation is DESIG094"""
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        global_db = client['Global']
        diagnostics_collection = global_db['backend_diagnostics_profile']
        
        # Find all profiles with DESIG094 designation
        doctors = list(diagnostics_collection.find(
            {"designation": "DESIG094"},
            {"employeeId": 1, "employeeName": 1, "_id": 0}
        ))
        
        return Response(doctors, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def doctor_schedule_list(request):
    """Get list of all doctors with their schedule details"""
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        
        # Get all doctors from diagnostics profile
        global_db = client['Global']
        diagnostics_collection = global_db['backend_diagnostics_profile']
        doctors_cursor = diagnostics_collection.find(
            {"designation": "DESIG094"},
            {"employeeId": 1, "employeeName": 1, "department": 1, "specialty": 1, "_id": 0} 
        )
        doctors = list(doctors_cursor)
        
        # Get schedules for these doctors
        hms_db = client['HMS']
        doctor_collection = hms_db['hospital_doctor']
        
        detailed_doctors = []
        for doc in doctors:
            employee_id = doc.get('employeeId')
            
            # Default values with name parsing
            emp_name = doc.get('employeeName', '')
            name_parts = emp_name.split(' ')
            first_name = name_parts[0] if name_parts else ''
            last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
            
            doc_data = {
                "employeeId": employee_id,
                "first_name": first_name,
                "middle_name": "", # Not available in simple split
                "last_name": last_name,
                "employeeName": emp_name,
                "department": doc.get('department'),
                "specialty": doc.get('specialty', 'General'),
                "consulting_fee": 0,
                "registration_fee": 0, 
                "renewal_fee": 0,
                "schedule_exists": False
            }
            
            # Fetch schedule
            schedule = doctor_collection.find_one({"employeeId": employee_id})
            if schedule:
                doc_data.update({
                    "consulting_fee": schedule.get("consulting_fee", 0),
                    "renewal_fee": schedule.get("renewal_fee", 0),
                    "registration_fee": schedule.get("renewal_fee", 0), # Mapping renewal_fee to registration_fee for frontend
                    "day_schedule": schedule.get("day_schedule", []),
                    "time_schedule": schedule.get("time_schedule", []),
                    "schedule_exists": True
                })
                
                # Convert Decimal128
                convert_decimal128_to_float(doc_data)
                detailed_doctors.append(doc_data)
            
        return Response(detailed_doctors, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def doctor_schedule_detail(request, employee_id):
    """Get doctor schedule details by employeeId from both collections"""
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        
        # Get from diagnostics profile
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
        
        # Get from hospital_doctor if exists
        hms_db = client['HMS']
        doctor_collection = hms_db['hospital_doctor']
        doctor_schedule = doctor_collection.find_one({"employeeId": employee_id})
        
        # Prepare response data
        response_data = {
            "employeeId": diagnostic_profile.get("employeeId"),
            "employeeName": diagnostic_profile.get("employeeName"),
            "email": diagnostic_profile.get("email"),
            "mobileNumber": diagnostic_profile.get("mobileNumber"),
            "department": diagnostic_profile.get("department"),
            "designation": diagnostic_profile.get("designation"),
            "consulting_fee": "",
            "renewal_fee": "",
            "day_schedule": [],
            "time_schedule": []
        }
        
        # If schedule exists, populate with existing data
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
        
        # Verify doctor exists in diagnostics profile
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
        # Prepare schedule data
        schedule_data = {
            "employeeId": employee_id,
            "consulting_fee": request.data.get("consulting_fee", ""),
            "renewal_fee": request.data.get("renewal_fee", ""),
            "day_schedule": request.data.get("day_schedule", []),
            "time_schedule": request.data.get("time_schedule", []),
            "created_by": created_by,
            "created_date":datetime.utcnow(),
            "hospital_code": hospital_code,
            "branch_code": branch_code
        }
        
        # Check if schedule exists
        hms_db = client['HMS']
        doctor_collection = hms_db['hospital_doctor']
        existing_schedule = doctor_collection.find_one({"employeeId": employee_id})
        
        if existing_schedule:
            # Update existing schedule
            result = doctor_collection.update_one(
                {"employeeId": employee_id},
                {"$set": schedule_data}
            )
            message = "Doctor schedule updated successfully"
        else:
            # Create new schedule
            doctor_collection.insert_one(schedule_data)
            message = "Doctor schedule created successfully"
        
        # Return updated data
        updated_schedule = doctor_collection.find_one({"employeeId": employee_id})
        response_data = {key: updated_schedule[key] for key in updated_schedule if key != '_id'}
        response_data = convert_decimal128_to_float(response_data)
        response_data["message"] = message
        
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
