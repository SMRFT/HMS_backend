from django.shortcuts import render
from datetime import datetime, time
from django.db.models import Q
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from django.utils import timezone
from pymongo import MongoClient
from django.utils.timezone import now
from rest_framework.parsers import MultiPartParser, FormParser
from bson import Decimal128
import json
from django.views.decorators.csrf import csrf_exempt

# Auth/permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import AllowAny
from pyauth.auth import HasRoleAndDataPermission

import os
from dotenv import load_dotenv
load_dotenv()
    
from .models import Billing, TempPatientRegistration

from .models import Billing
from .serializers import PatientSerializer
@api_view(['GET', 'POST'])
@csrf_exempt
@permission_classes([HasRoleAndDataPermission])
def patientCreateView(request):
    # Extract audit info from headers
    employee_id = (
        request.data.get('auth-user-id') or
        request.headers.get('auth-user-id') or
        "system"
    )
    print("Employee ID:", employee_id)
    hospital_code = (
        request.data.get('hospital-code') or
        request.headers.get('hospital-code') or
        "system"
    )
    print("Hospital Code:", hospital_code)

    if request.method == 'GET':
        uhid = request.GET.get('uhid')
        ip_number = request.GET.get('ip_number')
        mobile = request.GET.get('mobile')

        # Filter based on parameters
        if uhid:
            patients = Patient.objects.filter(uhid=uhid)
        elif ip_number:
            patients = Patient.objects.filter(ip_number=ip_number)
        elif mobile:
            patients = Patient.objects.filter(mobilePhone=mobile)
        else:
            patients = Patient.objects.all()

        serializer = PatientSerializer(patients, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        print("Received POST data:", request.data)
        
        uhid = request.data.get('uhid')
        patient = None

        if uhid:
            try:
                patient = Patient.objects.get(uhid=uhid)
                print(f"Found existing patient: {patient}")
                serializer = PatientSerializer(patient, data=request.data, partial=True)
            except Patient.DoesNotExist:
                print(f"Patient with UHID {uhid} not found. Creating new...")
                serializer = PatientSerializer(data=request.data)
        else:
            print("No UHID provided. Creating new patient...")
            serializer = PatientSerializer(data=request.data)

        if serializer.is_valid():
            print("Serializer Valid. Saving...")
            try:
                # Set audit fields before saving
                save_kwargs = {
                    'lastmodified_by': employee_id,
                    'hospital_code': hospital_code
                }
                if not serializer.instance:
                    save_kwargs['created_by'] = employee_id
                    
                patient = serializer.save(**save_kwargs)
                print("Patient Saved:", patient)
            except Exception as e:
                print("Error saving patient:", e)
                import traceback
                traceback.print_exc()
                raise e


            # ✅ Automatically create Billing record
            registration_fee = clean_decimal(request.data.get('registrationFee'))
            consulting_fee = clean_decimal(request.data.get('consultingFee'))
            total_fees = clean_decimal(request.data.get('totalFees'))
            payment_method = request.data.get('payment_method', None)
            doctor_id = request.data.get('employeeId', None)

            Billing.objects.create(
                patient=patient,
                registration_fee=registration_fee,
                consulting_fee=consulting_fee,
                total_fees=total_fees,
                payment_method=payment_method,
                doctor_id=doctor_id,
                created_by=employee_id,
                lastmodified_by=employee_id,
                hospital_code=hospital_code
            )

            return Response({
                "message": "Patient registered successfully.",
                "uhid": patient.uhid,
                "patient": serializer.data
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


    

from bson import Decimal128
# Helper function to convert Decimal128 fields to float
def convert_decimal128_to_float(data):
    for key, value in data.items():
        if isinstance(value, Decimal128):
            data[key] = float(value.to_decimal())
        elif isinstance(value, dict):
            convert_decimal128_to_float(value)  # Recurse if nested dict
    return data







from .models import Summary
from .serializers import SummarySerializer

@api_view(['GET'])
def get_summaries(request):
    summaries = Summary.objects.all()
    serializer = SummarySerializer(summaries, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)




from rest_framework.response import Response
from rest_framework.decorators import api_view
from .models import Patient
from .serializers import PatientSerializer

@api_view(['GET'])
def op_patient_detail_by_uhid(request, uhid):
    try:
        patient = Patient.objects.get(uhid=uhid)
        serializer = PatientSerializer(patient)
        return Response(serializer.data)
    except Patient.DoesNotExist:
        return Response({"error": "Patient not found"}, status=404)

    

from rest_framework.response import Response
from rest_framework.decorators import api_view
from .models import Admission
from .serializers import AdmissionSerializer

@api_view(['GET'])
def ip_patient_detail_by_ipNumber(request, ipNumber):
    try:
        patient = Admission.objects.get(ipNumber=ipNumber)
        serializer = AdmissionSerializer(patient)
        return Response(serializer.data)
    except Admission.DoesNotExist:
        return Response({"error": "Patient not found"}, status=404)   
    
    



from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import ReferenceDoctor
from .serializers import ReferenceDoctorSerializer

# ✅ Save Reference Doctor (POST)
@api_view(['POST'])
def save_reference_doctor(request):
    serializer = ReferenceDoctorSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({"message": "Reference doctor saved successfully!"}, status=201)
    return Response(serializer.errors, status=400)

# ✅ Get All Reference Doctors (GET)
@api_view(['GET'])
def get_reference_doctors(request):
    doctors = ReferenceDoctor.objects.all()
    serializer = ReferenceDoctorSerializer(doctors, many=True)
    return Response(serializer.data, status=200)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_last_uhid(request):
    try:
        # Assuming typical Django auto-increment or similar logic, or explicit time field.
        # Since it's often user-provided or custom generated, we just want the latest record.
        # Order by uhid to get the highest sequential number
        last_patient = Patient.objects.all().order_by('-uhid').first()
        if last_patient:
            return Response({"uhid": last_patient.uhid}, status=200)
        return Response({"uhid": "None"}, status=200)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(['GET'])
def get_user_permissions(request):
    """
    Fetches specific page permissions for a user.
    Logic:
    1. Fetch 'primaryRole' and 'additionalRoles' from Global.backend_diagnostics_profile
    2. If 'HMS-P' is present in roles, fetch 'allowed_pages' from HMS.UserPageAccess
    3. Return combined list of roles + allowed_pages
    """
    employee_id = request.GET.get('employeeId')
    
    if not employee_id:
        return Response({"error": "Employee ID is required"}, status=400)

    try:
        mongo_host = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_host)
        
        # 1. Fetch Roles from Global DB
        global_db = client['Global']
        diag_collection = global_db['backend_diagnostics_profile']
        user_profile = diag_collection.find_one(
            {"employeeId": employee_id},
            {"primaryRole": 1, "additionalRoles": 1, "hms_pages": 1, "allowed_pages": 1, "_id": 0}
        )
        
        roles = []
        hms_pages = []
        extra_permissions = []
        if user_profile:
            p_role = user_profile.get("primaryRole")
            a_roles = user_profile.get("additionalRoles", [])
            hms_pages = user_profile.get("hms_pages", [])
            
            if p_role:
                roles.append(p_role)
            if isinstance(a_roles, list):
                roles.extend(a_roles)
                
        # 2. Check for 'HMS-P' and fetch extra permissions
        if "HMS-P" in roles and user_profile:
            extra_permissions = user_profile.get("allowed_pages", [])

        # 3. Combine and return
        # Logic: If extra_permissions exist, we prioritize them over roles for HMS-specific pages.
        if extra_permissions:
            combined_permissions = list(set(extra_permissions))
        else:
            combined_permissions = list(set(roles))
        
        return Response({
            "employeeId": employee_id, 
            "allowed_pages": combined_permissions,
            "roles": list(set(roles)),
            "hms_pages": list(set(hms_pages)) if isinstance(hms_pages, list) else []
        }, status=200)

    except Exception as e:
        print(f"Error fetching user permissions: {e}")
        return Response({"error": "Internal Server Error: " + str(e)}, status=500)

@api_view(['POST'])
def update_user_permissions(request):
    """
    Updates the list of allowed pages for a specific employee.
    Expects JSON body: { "employeeId": "...", "allowed_pages": ["...", "..."] }
    """
    try:
        employee_id = request.data.get('employeeId')
        allowed_pages = request.data.get('allowed_pages')

        if not employee_id:
            return Response({"error": "Employee ID is required"}, status=400)
        
        if allowed_pages is None or not isinstance(allowed_pages, list):
            return Response({"error": "allowed_pages must be a list"}, status=400)

        mongo_host = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_host)
        global_db = client['Global']
        diag_collection = global_db['backend_diagnostics_profile']

        update_fields = {
            "allowed_pages": allowed_pages
        }

        hms_pages = request.data.get('hms_pages')
        if isinstance(hms_pages, list):
            update_fields["hms_pages"] = hms_pages

        # Upsert the permission record into the Global database
        result = diag_collection.update_one(
            {"employeeId": employee_id},
            {"$set": update_fields},
            upsert=True
        )

        return Response({
            "message": "Permissions updated successfully",
            "employeeId": employee_id,
            "allowed_pages": allowed_pages
        }, status=200)

    except Exception as e:
        print(f"Error updating user permissions: {e}")
        return Response({"error": str(e)}, status=500)


from rest_framework.decorators import api_view
from rest_framework.response import Response
from pymongo import MongoClient
import os


@api_view(['GET'])
def get_all_employees(request):
    """
    Fetch employees who have ANY role starting with 'HMS'
    (primaryRole or additionalRoles).
    """

    try:
        mongo_host = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_host)

        global_db = client['Global']
        diag_collection = global_db['backend_diagnostics_profile']

        # 🔥 Match roles starting with "HMS"
        query = {
            "$or": [
                {"primaryRole": {"$regex": "^HMS"}},
                {"additionalRoles": {"$elemMatch": {"$regex": "^HMS"}}}
            ]
        }

        employees = list(diag_collection.find(
            query,
            {
                "employeeId": 1,
                "employeeName": 1,
                "designation": 1,
                "_id": 0
            }
        ))

        client.close()
        return Response(employees, status=200)

    except Exception as e:
        print(f"Error fetching employees: {e}")
        return Response({"error": str(e)}, status=500)

from .models import Billing
from .serializers import BillingSerializer
from decimal import Decimal

def clean_decimal(value):
    if value is None or value == "":
        return None
    
    if isinstance(value, (int, float, Decimal)):
        return value
        
    # Force to string for cleaning to handle types like Decimal128 or dirty strings
    # This prevents values from unknown types from falling through to the catch-all 0.0
    s_value = str(value)
    
    # Remove smart quotes and commas
    s_value = s_value.replace('“', '').replace('”', '').replace('"', '').replace(',', '')
    
    try:
        return float(s_value)
    except (ValueError, TypeError):
        return 0.0

@api_view(['GET'])
def registration_bills(request):
    try:
        # Get all billing records, ordered by billed_date descending
        bills = Billing.objects.select_related('patient').all().order_by('-billed_date')
        serializer = BillingSerializer(bills, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['PATCH'])
def update_bill_status(request, bill_number):
    employee_id = request.headers.get('auth-user-id', 'system')
    hospital_code = request.headers.get('hospital-code', 'system')

    try:
        bill = Billing.objects.get(bill_number=bill_number)

        # Clean existing fee fields before saving to fix legacy data issues
        bill.registration_fee = clean_decimal(bill.registration_fee)
        bill.consulting_fee = clean_decimal(bill.consulting_fee)
        bill.total_fees = clean_decimal(bill.total_fees)
        


        payment_status = request.data.get('payment_status')

        if payment_status:
            if payment_status not in ['Paid', 'Pending', 'Unpaid']:
                return Response({"error": "Invalid payment status"}, status=status.HTTP_400_BAD_REQUEST)
            bill.payment_status = payment_status
            
            if payment_status == 'Paid':
                bill.paid_date = timezone.now()
            else:
                bill.paid_date = None

        payment_method = request.data.get('payment_method')
        transaction_id = request.data.get('transaction_id')

        # Allow updating payment details regardless of status, but enforce logic if needed
        if payment_method:
            bill.payment_method = payment_method
        
        if transaction_id:
            bill.transaction_id = transaction_id
            
        # Update audit fields
        bill.lastmodified_by = employee_id
        bill.hospital_code = hospital_code
        bill.save()
        
        serializer = BillingSerializer(bill)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Billing.DoesNotExist:
        return Response({"error": "Bill not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def patient_registration_stats(request):
    try:
        from_date_str = request.GET.get('fromDate')
        to_date_str = request.GET.get('toDate')
        doctor_id = request.GET.get('doctorId')

        # Get current date for defaults
        today = timezone.now().date()

        if from_date_str:
             from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        else:
             from_date = today

        if to_date_str:
             to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        else:
             to_date = today
        
        # Safe construction using timezone helper if needed
        # We assume USE_TZ=True or configured correctly.
        # timezone.make_aware requires naive datetime.
        
        start_naive = datetime.combine(from_date, time.min)
        end_naive = datetime.combine(to_date, time.max)
        
        if timezone.is_naive(start_naive):
            start_dt = timezone.make_aware(start_naive)
        else:
            start_dt = start_naive
            
        if timezone.is_naive(end_naive):
            end_dt = timezone.make_aware(end_naive)
        else:
            end_dt = end_naive

        # Base filter for Bills
        bill_filter = Q(billed_date__range=(start_dt, end_dt))
        
        if doctor_id:
            bill_filter &= Q(doctor_id=doctor_id)
            
        bills = Billing.objects.filter(bill_filter).select_related('patient')
        
        total_visits = bills.count()
        new_visit_count = 0
        existing_visit_count = 0
        
        # Optimization: fetch patient dates in a list/dict if needed, but iteration is fine for moderate scale
        for bill in bills:
            if not hasattr(bill, 'patient') or bill.patient is None:
                print(f"Warning: Bill {bill.bill_number} has no patient reference.")
                existing_visit_count += 1
                continue

            p_created = bill.patient.created_date
            
            if p_created is None:
                # If no created_date, treat as old patient
                existing_visit_count += 1
                continue

            # Ensure p_created is aware for comparison
            if timezone.is_naive(p_created):
                p_created = timezone.make_aware(p_created)
                
            # Logic: If patient created in range (>= start_dt), it's a new registration
            if p_created >= start_dt:
                 new_visit_count += 1
            else:
                 existing_visit_count += 1
                 
        return Response({
            "new_visit": new_visit_count,
            "existing_visit": existing_visit_count,
            "total_visit": total_visits
        })

    except Exception as e:
        print(f"Error in stats: {e}")
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)


@api_view(['GET'])
def patient_visit_list(request):
    try:
        from_date_str = request.GET.get('fromDate')
        to_date_str = request.GET.get('toDate')
        doctor_id = request.GET.get('doctorId')

        today = timezone.now().date()

        if from_date_str:
             from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        else:
             from_date = today

        if to_date_str:
             to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        else:
             to_date = today
        
        start_naive = datetime.combine(from_date, time.min)
        end_naive = datetime.combine(to_date, time.max)
        
        if timezone.is_naive(start_naive):
             start_dt = timezone.make_aware(start_naive)
        else:
             start_dt = start_naive
             
        if timezone.is_naive(end_naive):
             end_dt = timezone.make_aware(end_naive)
        else:
             end_dt = end_naive

        bill_filter = Q(billed_date__range=(start_dt, end_dt))
        if doctor_id:
            bill_filter &= Q(doctor_id=doctor_id)

        bills = Billing.objects.filter(bill_filter).select_related('patient').order_by('-billed_date')
        
        data = []
        for bill in bills:
            if not hasattr(bill, 'patient') or bill.patient is None:
                print(f"Warning: Bill {bill.bill_number} has no patient.")
                continue

            p_created = bill.patient.created_date
            if p_created and timezone.is_naive(p_created):
                p_created = timezone.make_aware(p_created)
            
            if p_created and start_dt:
                visit_type = "New" if p_created >= start_dt else "Review"
            else:
                visit_type = "Review"
            
            p = bill.patient
            full_name = f"{p.salutation or ''} {p.firstName or ''} {p.lastName or ''}".strip()
            
            # Formatting address safely
            address_parts = [
                p.permanent_address,
                p.area,
                p.city,
                p.state,
                p.zipcode
            ]
            full_address = ", ".join([str(val) for val in address_parts if val]).strip()

            data.append({
                "uhid": p.uhid,
                "patientName": full_name,
                "age": p.age,
                "gender": p.gender,
                "mobile": p.mobilePhone,
                "doctor": bill.doctor_id, 
                "doctorName": p.doctorName or '',
                "spouseName": p.spouse_name or '',
                "address": full_address,
                "visitType": visit_type,
                "billNumber": bill.bill_number,
                "registrationFee": str(bill.registration_fee or 0),
                "consultingFee": str(bill.consulting_fee or 0),
                "billAmount": str(bill.total_fees or 0),
                "paymentStatus": bill.payment_status,
                "paymentMethod": bill.payment_method or 'Cash',
                "date": bill.billed_date.strftime("%d-%m-%Y %I:%M %p") if bill.billed_date else ''
            })
            
        return Response(data)
        
    except Exception as e:
        print(f"Error in visit list: {e}")
        return Response({"error": str(e)}, status=500)


# QR Registration Views
import uuid
from .models import TempPatientRegistration

@api_view(['GET'])
def generate_qr_session(request):
    try:
        session_id = str(uuid.uuid4())
        # We can pre-create the entry or just let the submission create it.
        # Creating it ensures we can track state if needed.
        TempPatientRegistration.objects.create(session_id=session_id, data="{}")
        return Response({"session_id": session_id})
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['POST'])
@permission_classes([AllowAny]) # Public endpoint for patient
def submit_qr_registration(request):
    try:
        session_id = request.data.get('session_id')
        form_data = request.data.get('data')
        
        if not form_data:
            return Response({"error": "Missing data"}, status=400)
            
        temp_reg = None
        if session_id:
            temp_reg = TempPatientRegistration.objects.filter(session_id=session_id).first()
            
        if not temp_reg:
            session_id = str(uuid.uuid4())
            temp_reg = TempPatientRegistration(session_id=session_id)
             
        temp_reg.data = json.dumps(form_data)
        temp_reg.is_consumed = False
        temp_reg.save()
        
        return Response({"message": "Submitted successfully"})
    except Exception as e:
        print(f"Error submitting qr reg: {e}")
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
def check_qr_status(request):
    try:
        session_id = request.GET.get('session_id')
        if not session_id:
             return Response({"error": "Missing session_id"}, status=400)
             
        temp_reg = TempPatientRegistration.objects.filter(session_id=session_id).first()
        
        if not temp_reg:
             return Response({"status": "invalid"}, status=404)
        
        data_str = temp_reg.data
        if data_str == "{}":
             return Response({"status": "waiting"})
             
        return Response({
            "status": "completed",
            "data": json.loads(data_str)
        })
        
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
def get_pending_qr_registrations(request):
    try:
        status = request.GET.get('status', 'pending')
        
        # Base query
        query = TempPatientRegistration.objects.all().order_by('-created_at')
        
        # Filter unless 'all' is requested
        if status != 'all':
            query = query.filter(is_consumed=False)
            
        pending = query
        results = []
        for p in pending:
            try:
                data = json.loads(p.data)
                # Only include if it has actua form data (e.g. mobilePhone is present)
                if data and 'mobilePhone' in data:
                    results.append({
                        "session_id": p.session_id,
                        "name": f"{data.get('firstName', '')} {data.get('lastName', '')}".strip() or "Unknown",
                        "mobile": data.get('mobilePhone', ''),
                        "age_gender": f"{data.get('age', '')}/{data.get('gender', '')}",
                        "timestamp": p.created_at,
                        "full_data": data,
                        "is_consumed": p.is_consumed
                    })
            except:
                pass
        return Response(results)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['POST'])
def consume_qr_registration(request):
    try:
        session_id = request.data.get('session_id')
        if not session_id:
            return Response({"error": "Missing session_id"}, status=400)
            
        temp_reg = TempPatientRegistration.objects.filter(session_id=session_id).first()
        if not temp_reg:
            return Response({"error": "Not found"}, status=404)
            
        temp_reg.is_consumed = True
        temp_reg.save()
        return Response({"message": "Consumed"})
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
def get_sidebar_mapping(request):
    """
    Fetch sidebar mapping filtered by permissions
    """

    employee_id = request.GET.get('employeeId')

    if employee_id in [None, "", "null", "undefined"]:
        employee_id = None

    try:
        mongo_host = os.getenv("GLOBAL_DB_HOST")
        if not mongo_host:
            return Response({"error": "Database configuration missing"}, status=500)

        client = MongoClient(mongo_host, serverSelectionTimeoutMS=5000)
        db = client['HMS']

        # 🔹 Fetch all mappings
        mapping_collection = db['frontendendpagemapping']
        all_groups = list(
            mapping_collection.find({}, {'_id': 0}).sort('order', 1)
        )

        # 🔹 No employee → return all
        if not employee_id:
            client.close()
            return Response(all_groups, status=200)

        # 🔹 Fetch roles
        global_db = client['Global']
        diag_collection = global_db['backend_diagnostics_profile']

        user_profile = diag_collection.find_one(
            {"employeeId": employee_id},
            {"primaryRole": 1, "additionalRoles": 1, "allowed_pages": 1, "_id": 0}
        )

        roles = []
        if user_profile:
            if user_profile.get("primaryRole"):
                roles.append(user_profile["primaryRole"])
            roles.extend(user_profile.get("additionalRoles", []))

        print("ROLES:", roles)  # 🔍 debug

        # 🔹 Extra permissions (optional)
        extra_permissions = []
        if any(r.startswith("HMS-P") for r in roles) and user_profile:
            extra_permissions = user_profile.get("allowed_pages", [])

        allowed_actions = extra_permissions if extra_permissions else roles

        print("ALLOWED:", allowed_actions)  # 🔍 debug

        # ============================================================
        # 🔥 PERMISSION EXPANSION (FIXED)
        # ============================================================

        # Step 1: Collect all permissions
        all_permissions = set()
        for group in all_groups:
            for page in group.get('pages', []):
                all_permissions.update(page.get('permissions', []))

        # Step 2: Check HMS access
        has_hms_access = any(role.startswith("HMS") for role in allowed_actions)

        expanded_permissions = set()

        if has_hms_access:
            # ✅ FULL HMS ACCESS
            for perm in all_permissions:
                if perm.startswith("HMS"):
                    expanded_permissions.add(perm)
        else:
            # ✅ Normal role logic
            for action in allowed_actions:
                expanded_permissions.add(action)

                for perm in all_permissions:
                    if perm.startswith(action + "-"):
                        expanded_permissions.add(perm)

        # ============================================================
        # 🔹 FILTER SIDEBAR
        # ============================================================

        filtered_groups = []

        for group in all_groups:
            allowed_pages = []

            for page in group.get('pages', []):
                page_perms = page.get('permissions', [])

                # No permission → allow
                if not page_perms:
                    allowed_pages.append(page)
                    continue

                # Match
                if set(page_perms) & expanded_permissions:
                    allowed_pages.append(page)

            if allowed_pages:
                new_group = group.copy()
                new_group['pages'] = allowed_pages
                filtered_groups.append(new_group)

        client.close()
        return Response(filtered_groups, status=200)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)

@api_view(['POST'])
def update_sidebar_mapping(request):
    """
    Updates the dynamic sidebar mapping structure in MongoDB.
    """
    try:
        updated_mapping = request.data.get('mapping', [])
        if not isinstance(updated_mapping, list):
            return Response({"error": "Invalid data format. Expected a list."}, status=400)
            
        mongo_host = os.getenv("GLOBAL_DB_HOST")
        if not mongo_host:
            return Response({"error": "Database configuration missing"}, status=500)

        client = MongoClient(mongo_host, serverSelectionTimeoutMS=5000)
        db = client['HMS']
        collection = db['frontendendpagemapping']
        
        # Clear existing mappings and insert the new ones
        collection.delete_many({})
        if updated_mapping:
            collection.insert_many(updated_mapping)
            
        client.close()
        return Response({"message": "Sidebar mapping updated successfully."}, status=200)
    except Exception as e:
        print(f"Error in update_sidebar_mapping: {e}")
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)
