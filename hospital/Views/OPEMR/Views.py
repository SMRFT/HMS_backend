import os
from pymongo import MongoClient
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from bson import Decimal128
from django.utils.timezone import now
from hospital.models import Patient, Billing
from .models import VitalEntry,  OPDoctorConsultation
from .serializer import VitalEntrySerializer,  OPDoctorConsultationSerializer


# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission, HasRolePermission
from rest_framework.decorators import api_view, permission_classes
from ..dbcollection import Diagnostics_test_details, HMS_Symptoms_list,medicine_package, profile_collection, doctor_role_code







def safe_float(val):
    if val is None:
        return 0.0
    if isinstance(val, Decimal128):
        return float(val.to_decimal())
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_get_billing_patient(request):
    """
    Get patient details for paid billed patients only using Django ORM Billing and Patient models.
    """
    try:

        data = request.data
        employee_id = data.get("auth-user-id")
        # Query all bills (Paid and Pending) via Django ORM Billing model (no doctor filter)
        paid_bills = Billing.objects.filter(payment_status__in=['Paid', 'paid', 'Pending', 'pending', 'Unpaid', 'unpaid']).select_related('patient').order_by('-billed_date')


        result = []
        for bill in paid_bills:
            patient_obj = getattr(bill, 'patient', None)
            if not patient_obj:
                continue

            salutation = getattr(patient_obj, 'salutation', '') or ''
            first_name = getattr(patient_obj, 'firstName', '') or ''
            last_name = getattr(patient_obj, 'lastName', '') or ''
            full_name = f"{salutation} {first_name} {last_name}".strip()

            doctor_id = getattr(bill, 'doctor_id', '') or ''
            from hospital.Views.dbcollection import get_employee_name_by_id
            doctor_name = get_employee_name_by_id(doctor_id)

            patient_data = {
                "id": getattr(patient_obj, 'id', None),
                "uhid": getattr(patient_obj, 'uhid', '') or '',
                "salutation": salutation,
                "firstName": first_name,
                "lastName": last_name,
                "patient_name": full_name or f"Patient ({getattr(patient_obj, 'uhid', '')})",
                "age": getattr(patient_obj, 'age', None),
                "gender": getattr(patient_obj, 'gender', '') or '',
                "dob": str(patient_obj.dob) if getattr(patient_obj, 'dob', None) else '',
                "mobilePhone": getattr(patient_obj, 'mobilePhone', '') or '',
                "blood_group": getattr(patient_obj, 'blood_group', '') or '',
                "city": getattr(patient_obj, 'city', '') or '',
                "permanent_address": getattr(patient_obj, 'permanent_address', '') or '',
                "doctorName": doctor_name,
                "emergency_contact": getattr(patient_obj, 'emergency_contact', '') or '',
            }

            billed_d = getattr(bill, 'billed_date', None)
            billed_date_str = billed_d.isoformat() if billed_d else ""

            latest_vital = None
            is_completed_today = False
            uhid_str = patient_data.get("uhid")
            if uhid_str:
                vital_entries = list(VitalEntry.objects.filter(uhid=uhid_str).order_by('-created_date')[:1])
                vital_entry_obj = vital_entries[0] if vital_entries else None
                if vital_entry_obj:
                    latest_vital = VitalEntrySerializer(vital_entry_obj).data
                    
                    if getattr(vital_entry_obj, 'created_date', None):
                        from django.utils import timezone
                        if vital_entry_obj.created_date.date() == timezone.now().date():
                            is_completed_today = True

            result.append({
                "bill_number": getattr(bill, 'bill_number', ''),
                "billed_date": billed_date_str,
                "payment_status": getattr(bill, 'payment_status', 'Paid'),
                "total_fees": safe_float(getattr(bill, 'total_fees', None)),
                "registration_fee": safe_float(getattr(bill, 'registration_fee', None)),
                "consulting_fee": safe_float(getattr(bill, 'consulting_fee', None)),
                "payment_method": getattr(bill, 'payment_method', '') or '',
                "doctor_id": getattr(bill, 'doctor_id', '') or '',
                "patient": patient_data,
                "vital_entry": latest_vital,
                "vital_status": "Completed" if is_completed_today else "Pending"
            })

        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_VitalEntry(request):
    """
    GET: Retrieve list of VitalEntry records (optionally filtered by ?uhid=... or auth-user-id matching doctor_id)
    POST: Create a new VitalEntry record using VitalEntrySerializer
    """
    if request.method == 'GET':
        uhid = request.query_params.get('uhid')
        employee_id = request.headers.get('auth-user-id') 
        if not employee_id and hasattr(request, 'data') and isinstance(request.data, dict):
            employee_id = request.data.get('auth-user-id')

        today_start = now().replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        today_end = today_start + timedelta(days=1)
        
        paid_bills = Billing.objects.filter(
            payment_status__in=['Paid', 'paid', 'Pending', 'pending', 'Unpaid', 'unpaid'],
            billed_date__gte=today_start,
            billed_date__lt=today_end
        ).select_related('patient').order_by('-billed_date')

        if employee_id:
            emp_str = str(employee_id).strip()
            paid_bills = paid_bills.filter(doctor_id=emp_str)

        result = []
        seen_uhids = set()

        for bill in paid_bills:
            patient_obj = getattr(bill, 'patient', None)
            if not patient_obj:
                continue

            patient_uhid = getattr(patient_obj, 'uhid', '') or ''
            if uhid and patient_uhid != uhid:
                continue

            salutation = getattr(patient_obj, 'salutation', '') or ''
            first_name = getattr(patient_obj, 'firstName', '') or ''
            last_name = getattr(patient_obj, 'lastName', '') or ''
            full_name = f"{salutation} {first_name} {last_name}".strip()

            patient_data = {
                "id": getattr(patient_obj, 'id', None),
                "uhid": patient_uhid,
                "salutation": salutation,
                "firstName": first_name,
                "lastName": last_name,
                "patient_name": full_name or f"Patient ({patient_uhid})",
                "age": getattr(patient_obj, 'age', None),
                "gender": getattr(patient_obj, 'gender', '') or '',
                "dob": str(patient_obj.dob) if getattr(patient_obj, 'dob', None) else '',
                "mobilePhone": getattr(patient_obj, 'mobilePhone', '') or '',
                "blood_group": getattr(patient_obj, 'blood_group', '') or '',
                "city": getattr(patient_obj, 'city', '') or '',
                "permanent_address": getattr(patient_obj, 'permanent_address', '') or '',
                "doctorName": getattr(patient_obj, 'doctorName', '') or '',
                "emergency_contact": getattr(patient_obj, 'emergency_contact', '') or '',
            }

            billed_d = getattr(bill, 'billed_date', None)
            billed_date_str = billed_d.isoformat() if billed_d else ""

            latest_vital = None
            is_completed_today = False
            if patient_uhid:
                vital_entries = list(VitalEntry.objects.filter(uhid=patient_uhid).order_by('-created_date')[:1])
                vital_entry_obj = vital_entries[0] if vital_entries else None
                if vital_entry_obj:
                    latest_vital = VitalEntrySerializer(vital_entry_obj).data
                    
                    if getattr(vital_entry_obj, 'created_date', None):
                        from django.utils import timezone
                        if vital_entry_obj.created_date.date() == timezone.now().date():
                            is_completed_today = True

            seen_uhids.add(patient_uhid)
            result.append({
                "bill_number": getattr(bill, 'bill_number', ''),
                "billed_date": billed_date_str,
                "payment_status": getattr(bill, 'payment_status', 'Paid'),
                "total_fees": safe_float(getattr(bill, 'total_fees', None)),
                "registration_fee": safe_float(getattr(bill, 'registration_fee', None)),
                "consulting_fee": safe_float(getattr(bill, 'consulting_fee', None)),
                "payment_method": getattr(bill, 'payment_method', '') or '',
                "doctor_id": getattr(bill, 'doctor_id', '') or '',
                "patient": patient_data,
                "vital_entry": latest_vital,
                "vital_status": "Completed" if is_completed_today else "Pending"
            })

        # Also include any standalone VitalEntry records
        remaining_vitals = VitalEntry.objects.all()
        if uhid:
            remaining_vitals = remaining_vitals.filter(uhid=uhid)
        if employee_id:
            emp_str = str(employee_id).strip()
            remaining_vitals = remaining_vitals.filter(doctor_id=emp_str)

        for v in remaining_vitals.order_by('-created_date'):
            if not getattr(v, 'created_date', None):
                continue
            from django.utils import timezone
            if v.created_date.date() != timezone.now().date():
                continue
                
            if v.uhid in seen_uhids:
                continue
            seen_uhids.add(v.uhid)
            patient_obj = Patient.objects.filter(uhid=v.uhid).first()
            if patient_obj:
                salutation = getattr(patient_obj, 'salutation', '') or ''
                first_name = getattr(patient_obj, 'firstName', '') or ''
                last_name = getattr(patient_obj, 'lastName', '') or ''
                full_name = f"{salutation} {first_name} {last_name}".strip()
                patient_data = {
                    "id": getattr(patient_obj, 'id', None),
                    "uhid": getattr(patient_obj, 'uhid', '') or '',
                    "salutation": salutation,
                    "firstName": first_name,
                    "lastName": last_name,
                    "patient_name": full_name or f"Patient ({getattr(patient_obj, 'uhid', '')})",
                    "age": getattr(patient_obj, 'age', None),
                    "gender": getattr(patient_obj, 'gender', '') or '',
                    "dob": str(patient_obj.dob) if getattr(patient_obj, 'dob', None) else '',
                    "mobilePhone": getattr(patient_obj, 'mobilePhone', '') or '',
                    "doctorName": getattr(patient_obj, 'doctorName', '') or '',
                }
            else:
                patient_data = {
                    "uhid": v.uhid,
                    "patient_name": f"Patient ({v.uhid})"
                }

            result.append({
                "bill_number": "",
                "billed_date": v.vital_entry_date.isoformat() if v.vital_entry_date else "",
                "payment_status": "Paid",
                "doctor_id": v.doctor_id or "",
                "patient": patient_data,
                "vital_entry": VitalEntrySerializer(v).data,
                "vital_status": "Completed"
            })

        return Response(result, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        employee_id = data.get("auth-user-id") or data.get("created_by")
        if employee_id:
            data['created_by'] = employee_id
            data['lastmodified_by'] = employee_id

        serializer = VitalEntrySerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "message": "Vital entry saved successfully.",
                    "data": serializer.data
                },
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_get_symptoms(request):
    """
    Get symptoms list from HMS_Symptoms_list dbcollection.py.
    Returns array of unique symptoms alone.
    """
    try:
        docs = list(HMS_Symptoms_list.find({"is_active": True}))
        if not docs:
            docs = list(HMS_Symptoms_list.find({}))

        symptoms_set = set()
        for doc in docs:
            sym_list = doc.get("symptoms", [])
            if isinstance(sym_list, list):
                for s in sym_list:
                    if s and isinstance(s, str):
                        symptoms_set.add(s.strip())

        sorted_symptoms = sorted(list(symptoms_set))
        return Response({"symptoms": sorted_symptoms}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_get_diagnostics_tests(request):
    """
    Get diagnostics test details from Diagnostics_test_details dbcollection.py.
    Displays test_name in dropdown, but returns test_id to store upon selection.
    """
    try:
        docs = list(Diagnostics_test_details.find({"is_active": True}))

        if not docs:
            docs = list(Diagnostics_test_details.find({}))

        tests = []
        for doc in docs:
            t_id = doc.get("test_id")
            t_name = doc.get("test_name")
            if t_id is not None and t_name:
                tests.append({
                    "test_id": int(t_id) if str(t_id).isdigit() else t_id,
                    "test_name": str(t_name).strip(),
                    "department": doc.get("department", "") or "",
                    "shortcut": doc.get("shortcut", "") or "",
                    "MRP": safe_float(doc.get("MRP"))
                })

        tests.sort(key=lambda x: x["test_name"])
        return Response(tests, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_get_medicines(request):
    """
    Get medicines list from medicine_package (hospital_pharmacyitem) dbcollection.py.
    Displays item_name in dropdown, returns item_id to store upon selection.
    """
    try:
        docs = list(medicine_package.find({"is_active": True}))
        if not docs:
            docs = list(medicine_package.find({}))

        medicines = []
        for doc in docs:
            m_id = doc.get("item_id")
            m_name = doc.get("item_name")
            if m_id is not None and m_name:
                medicines.append({
                    "item_id": int(m_id) if str(m_id).isdigit() else m_id,
                    "item_name": str(m_name).strip(),
                    "category": doc.get("category", "") or "",
                    "chemical_composition": doc.get("chemical_composition", "") or ""
                })

        medicines.sort(key=lambda x: x["item_name"])
        return Response(medicines, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_DoctorConsultation(request):
    """
    GET: Retrieve doctor consultation records using DoctorConsultation model (filtered by ?uhid=...)
    POST: Save doctor consultation record using DoctorConsultation model and DoctorConsultationSerializer.
    """
    try:
        if request.method == 'GET':
            uhid = request.query_params.get('uhid')
            if uhid:
                records = OPDoctorConsultation.objects.filter(uhid=uhid).order_by('-created_date')
            else:
                records = OPDoctorConsultation.objects.all().order_by('-created_date')
            serializer = OPDoctorConsultationSerializer(records, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        elif request.method == 'POST':
            data = request.data
            uhid = data.get("uhid")
            if not uhid:
                return Response({"error": "uhid is required"}, status=status.HTTP_400_BAD_REQUEST)

            employee_id = data.get("auth-user-id")

            vitals_data = data.get("vitals", {})
            if isinstance(vitals_data, dict):
                vitals_data.pop('_id', None)
                vitals_data.pop('id', None)

            consult_data = {
                "uhid": uhid,
                "created_by": employee_id,
                "lastmodified_by": employee_id,
                "doctor_id": data.get("doctor_id", ""),
                "vitals": vitals_data,
                "pain_score": data.get("pain_score", None),
                "allergies": data.get("allergies", ""),
                "chief_complaints": data.get("chief_complaints", ""),
                "past_history": data.get("past_history", []),
                "present_medications": data.get("present_medications", ""),
                "symptoms": data.get("symptoms", []),
                "investigation_test_ids": data.get("investigation_test_ids", []),
                "investigation_details": data.get("investigation_details", []),
                "prescription_item_ids": data.get("prescription_item_ids", []),
                "prescription_details": data.get("prescription_details", []),
                "finding": data.get("finding", ""),
                "diet": data.get("diet", ""),
                "refer_to_doctor": data.get("refer_to_doctor", ""),
                "followup_date": data.get("followup_date", None),
                "consultation_start_time": data.get("consultation_start_time", None),
                "consultation_end_time": data.get("consultation_end_time", None)
            }

            today_start = now().replace(hour=0, minute=0, second=0, microsecond=0)
            ongoing_consult = OPDoctorConsultation.objects.filter(
                uhid=uhid,
                created_date__gte=today_start,
                consultation_end_time__isnull=True
            ).first()

            if ongoing_consult:
                serializer = OPDoctorConsultationSerializer(ongoing_consult, data=consult_data, partial=True)
            else:
                serializer = OPDoctorConsultationSerializer(data=consult_data)

            if serializer.is_valid():
                obj = serializer.save()
                return Response(
                    {
                        "message": "Doctor consultation saved successfully.",
                        "data": OPDoctorConsultationSerializer(obj).data
                    },
                    status=status.HTTP_201_CREATED
                )
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_get_vital_history(request):
    """
    Get full vital history for a given patient UHID.
    """
    uhid = request.query_params.get('uhid')
    if not uhid:
        return Response({"error": "UHID is required."}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        vitals = VitalEntry.objects.filter(uhid=uhid).order_by('-created_date')
        serializer = VitalEntrySerializer(vitals, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def OPEMR_get_referral_doctors(request):
    """
    Get all employees who have 'doctor_role_code' in their primaryRole or additionalRoles.
    """
    try:
        query = {
            "$or": [
                {"primaryRole": doctor_role_code},
                {"additionalRoles": doctor_role_code}
            ]
        }
        docs = list(profile_collection.find(query, {"employeeId": 1, "employeeName": 1, "_id": 0}))
        
        doctors = []
        for d in docs:
            if d.get("employeeId"):
                doctors.append({
                    "employeeId": d.get("employeeId", ""),
                    "employeeName": d.get("employeeName", "")
                })
                
        return Response({"success": True, "data": doctors}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def OPEMR_Vitaldashboard(request):
    """
    Get vital analytics and wait times for a specific date (defaults to today).
    """
    from datetime import datetime, timedelta
    from django.utils import timezone

    from_date_str = request.query_params.get('from_date')
    to_date_str = request.query_params.get('to_date')
    
    try:
        if from_date_str:
            start_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        else:
            start_date = timezone.now().date()
            
        if to_date_str:
            end_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        else:
            end_date = start_date
    except ValueError:
        return Response({"error": "Invalid date format. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

    today_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    today_end = timezone.make_aware(datetime.combine(end_date, datetime.min.time())) + timedelta(days=1)

    try:
        # 1. Fetch paid bills
        paid_bills = Billing.objects.filter(
            payment_status__iexact="paid",
            billed_date__gte=today_start,
            billed_date__lt=today_end
        ).select_related('patient')

        # 2. Fetch Vitals and Consultations
        vitals = VitalEntry.objects.filter(created_date__gte=today_start, created_date__lt=today_end)
        consultations = OPDoctorConsultation.objects.filter(created_date__gte=today_start, created_date__lt=today_end)

        vitals_by_uhid = {}
        for v in vitals:
            if v.uhid not in vitals_by_uhid or v.vital_entry_date > vitals_by_uhid[v.uhid].vital_entry_date:
                vitals_by_uhid[v.uhid] = v

        consults_by_uhid = {}
        for c in consultations:
            if c.uhid not in consults_by_uhid or c.created_date > consults_by_uhid[c.uhid].created_date:
                consults_by_uhid[c.uhid] = c

        patients_list = []
        total_vital_wait_time_mins = 0
        total_doc_wait_time_mins = 0
        vitals_count = 0
        consult_count = 0

        for bill in paid_bills:
            patient_obj = getattr(bill, 'patient', None)
            if not patient_obj:
                continue

            uhid = getattr(patient_obj, 'uhid', '') or ''
            if not uhid:
                continue

            salutation = getattr(patient_obj, 'salutation', '') or ''
            first_name = getattr(patient_obj, 'firstName', '') or ''
            last_name = getattr(patient_obj, 'lastName', '') or ''
            full_name = f"{salutation} {first_name} {last_name}".strip()

            billed_d = getattr(bill, 'billed_date', None)
            
            vital_obj = vitals_by_uhid.get(uhid)
            vital_d = vital_obj.vital_entry_date if vital_obj and vital_obj.vital_entry_date else None
            
            consult_obj = consults_by_uhid.get(uhid)
            consult_d = None
            if consult_obj:
                if getattr(consult_obj, 'consultation_start_time', None):
                    # It's an ISO string or datetime
                    c_start = consult_obj.consultation_start_time
                    if isinstance(c_start, str):
                        try:
                            # Handle standard ISO format and trailing Z
                            c_start = c_start.replace('Z', '+00:00')
                            consult_d = datetime.fromisoformat(c_start)
                        except ValueError:
                            pass
                    else:
                        consult_d = c_start

            vital_wait = None
            if billed_d and vital_d:
                vital_wait = int((vital_d - billed_d).total_seconds() / 60)
                if vital_wait < 0: vital_wait = 0
                total_vital_wait_time_mins += vital_wait
                vitals_count += 1

            doc_wait = None
            if vital_d and consult_d:
                doc_wait = int((consult_d - vital_d).total_seconds() / 60)
                if doc_wait < 0: doc_wait = 0
                total_doc_wait_time_mins += doc_wait
                consult_count += 1
            elif billed_d and consult_d:
                doc_wait = int((consult_d - billed_d).total_seconds() / 60)
                if doc_wait < 0: doc_wait = 0
                total_doc_wait_time_mins += doc_wait
                consult_count += 1

            patients_list.append({
                "uhid": uhid,
                "patient_name": full_name or f"Patient ({uhid})",
                "billed_date": billed_d.isoformat() if billed_d else None,
                "vital_date": vital_d.isoformat() if vital_d else None,
                "consultation_start": consult_d.isoformat() if consult_d else None,
                "vital_wait_mins": vital_wait,
                "doc_wait_mins": doc_wait
            })

        summary = {
            "total_billed": len(patients_list),
            "vitals_completed": vitals_count,
            "consultations_started": consult_count,
            "avg_vital_wait_mins": round(total_vital_wait_time_mins / vitals_count) if vitals_count > 0 else 0,
            "avg_doc_wait_mins": round(total_doc_wait_time_mins / consult_count) if consult_count > 0 else 0,
            "from_date": start_date.isoformat(),
            "to_date": end_date.isoformat()
        }

        # Sort patient list by billed date
        patients_list.sort(key=lambda x: x["billed_date"] or "", reverse=True)

        return Response({
            "success": True,
            "summary": summary,
            "patients": patients_list
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def OPEMR_patientlivetracking(request):
    """
    Get live tracking of all patients for today.
    """
    from datetime import datetime, timedelta
    from django.utils import timezone

    today_start = timezone.make_aware(datetime.combine(timezone.now().date(), datetime.min.time()))
    today_end = today_start + timedelta(days=1)

    try:
        # Fetch today's paid bills (Registered patients)
        paid_bills = Billing.objects.filter(
            payment_status__iexact="paid",
            billed_date__gte=today_start,
            billed_date__lt=today_end
        ).select_related('patient')

        vitals = VitalEntry.objects.filter(created_date__gte=today_start, created_date__lt=today_end)
        consultations = OPDoctorConsultation.objects.filter(created_date__gte=today_start, created_date__lt=today_end)

        vitals_by_uhid = {v.uhid: v for v in vitals}
        consults_by_uhid = {c.uhid: c for c in consultations}

        live_patients = []
        for bill in paid_bills:
            patient_obj = getattr(bill, 'patient', None)
            if not patient_obj:
                continue

            uhid = getattr(patient_obj, 'uhid', '')
            if not uhid:
                continue

            salutation = getattr(patient_obj, 'salutation', '') or ''
            first_name = getattr(patient_obj, 'firstName', '') or ''
            last_name = getattr(patient_obj, 'lastName', '') or ''
            full_name = f"{salutation} {first_name} {last_name}".strip()

            billed_d = getattr(bill, 'billed_date', None)
            vital_obj = vitals_by_uhid.get(uhid)
            consult_obj = consults_by_uhid.get(uhid)

            status = "Registered"
            status_color = "gray"
            consult_start = None
            consult_end = None
            
            if consult_obj:
                consult_start = getattr(consult_obj, 'consultation_start_time', None)
                consult_end = getattr(consult_obj, 'consultation_end_time', None)

                if consult_end:
                    status = "Completed"
                    status_color = "green"
                elif consult_start:
                    status = "In Consultation"
                    status_color = "blue"
                else:
                    status = "Waiting for Doctor"
                    status_color = "orange"
            elif vital_obj:
                status = "Waiting for Doctor"
                status_color = "orange"
            else:
                status = "Waiting for Vitals"
                status_color = "yellow"

            # Check-in time is billed_date
            checkin_time = billed_d.isoformat() if billed_d else None
            
            live_patients.append({
                "uhid": uhid,
                "patient_name": full_name or f"Patient ({uhid})",
                "doctor_id": getattr(bill, 'doctor_id', ''),
                "department": getattr(bill, 'department', 'OPD'),
                "status": status,
                "status_color": status_color,
                "checkin_time": checkin_time,
                "consult_start": consult_start if isinstance(consult_start, str) else (consult_start.isoformat() if consult_start else None),
                "consult_end": consult_end if isinstance(consult_end, str) else (consult_end.isoformat() if consult_end else None)
            })

        # Sort by checkin time descending
        live_patients.sort(key=lambda x: x["checkin_time"] or "", reverse=True)

        return Response({
            "success": True,
            "data": live_patients
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def OPEMR_docotordashboard(request):
    """
    Aggregated Analytics for the Doctor Dashboard.
    """
    from datetime import datetime, timedelta
    from django.utils import timezone

    from_date_str = request.query_params.get('from_date')
    to_date_str = request.query_params.get('to_date')
    
    if from_date_str and to_date_str:
        try:
            start_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
    else:
        date_str = request.query_params.get('date')
        if date_str:
            try:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                start_date = target_date
                end_date = target_date
            except ValueError:
                return Response({"error": "Invalid date format. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            start_date = timezone.now().date()
            end_date = start_date

    today_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    today_end = timezone.make_aware(datetime.combine(end_date, datetime.min.time())) + timedelta(days=1)
    
    # Yesterday for comparison (based on start_date)
    yesterday_start = today_start - timedelta(days=1)
    yesterday_end = today_start

    try:
        # Today's Bills
        today_bills = Billing.objects.filter(
            payment_status__iexact="paid",
            billed_date__gte=today_start,
            billed_date__lt=today_end
        )
        total_patients_today = today_bills.count()

        # Yesterday's Bills
        yesterday_bills = Billing.objects.filter(
            payment_status__iexact="paid",
            billed_date__gte=yesterday_start,
            billed_date__lt=yesterday_end
        )
        total_patients_yesterday = yesterday_bills.count()

        # Consultations Today
        today_consults = OPDoctorConsultation.objects.filter(
            created_date__gte=today_start,
            created_date__lt=today_end
        )
        
        completed_consults = 0
        total_consult_time_mins = 0
        first_consult_time = None
        last_consult_time = None

        for c in today_consults:
            c_start = getattr(c, 'consultation_start_time', None)
            c_end = getattr(c, 'consultation_end_time', None)
            
            if c_start and c_end:
                try:
                    if isinstance(c_start, str): c_start = datetime.fromisoformat(c_start.replace('Z', '+00:00'))
                    if isinstance(c_end, str): c_end = datetime.fromisoformat(c_end.replace('Z', '+00:00'))
                    
                    if not first_consult_time or c_start < first_consult_time:
                        first_consult_time = c_start
                    if not last_consult_time or c_start > last_consult_time:
                        last_consult_time = c_start
                        
                    duration_mins = int((c_end - c_start).total_seconds() / 60)
                    if duration_mins > 0:
                        total_consult_time_mins += duration_mins
                        completed_consults += 1
                except:
                    pass

        avg_consult_time = round(total_consult_time_mins / completed_consults) if completed_consults > 0 else 0

        # Peak Hour Analysis (Group by hour of billed_date)
        hourly_counts = {f"{i:02d}:00": 0 for i in range(8, 22)} # 8 AM to 9 PM
        for bill in today_bills:
            b_date = getattr(bill, 'billed_date', None)
            if b_date:
                hour_str = f"{b_date.hour:02d}:00"
                if hour_str in hourly_counts:
                    hourly_counts[hour_str] += 1
                else:
                    hourly_counts[hour_str] = 1

        peak_hour_data = [{"time": k, "patients": v} for k, v in hourly_counts.items() if v > 0 or (8 <= int(k[:2]) <= 20)]

        summary = {
            "total_patients_today": total_patients_today,
            "total_patients_yesterday": total_patients_yesterday,
            "avg_consult_time_mins": avg_consult_time,
            "completed_consults": completed_consults,
            "first_consult_time": first_consult_time.isoformat() if first_consult_time else None,
            "last_consult_time": last_consult_time.isoformat() if last_consult_time else None
        }

        # --- Doctor Level Metrics ---
        from hospital.models import Admission

        today_admissions = Admission.objects.filter(
            admissionDateTime__gte=today_start,
            admissionDateTime__lt=today_end
        )

        doctor_stats = {}

        # 1. OP Counts & Patients
        for bill in today_bills:
            doc_id = getattr(bill, 'doctor_id', None) or 'Unknown Doctor'
            patient = getattr(bill, 'patient', None)
            
            p_name = "Unknown Patient"
            if patient:
                p_name = f"{getattr(patient, 'salutation', '') or ''} {getattr(patient, 'firstName', '') or ''} {getattr(patient, 'lastName', '') or ''}".strip()
            
            if doc_id not in doctor_stats:
                doctor_stats[doc_id] = {"doctor_name": doc_id, "op_count": 0, "ip_count": 0, "consult_mins": 0, "patients": set()}
            
            doctor_stats[doc_id]["op_count"] += 1
            if p_name and p_name != "Unknown Patient":
                doctor_stats[doc_id]["patients"].add(p_name)

        # 2. IP Counts & Patients
        for adm in today_admissions:
            doc_id = getattr(adm, 'admittingDoctor', None)
            # You might want to consider consultingDoctor as well
            if not doc_id:
                doc_id = getattr(adm, 'consultingDoctor', None) or 'Unknown Doctor'

            # Patient name from Admission (or fetch from Patient if needed, but let's just use UHID for now or fetch patient)
            # Normally admission has uhid
            uhid = getattr(adm, 'uhid', '')
            p_name = f"IP Patient ({uhid})" if uhid else "IP Patient"
            
            if doc_id not in doctor_stats:
                doctor_stats[doc_id] = {"doctor_name": doc_id, "op_count": 0, "ip_count": 0, "consult_mins": 0, "patients": set()}
            
            doctor_stats[doc_id]["ip_count"] += 1
            doctor_stats[doc_id]["patients"].add(p_name)

        # 3. Consulting Time
        for c in today_consults:
            doc_id = getattr(c, 'doctor_name', None) or getattr(c, 'doctor_id', None) or 'Unknown Doctor'
            c_start = getattr(c, 'consultation_start_time', None)
            c_end = getattr(c, 'consultation_end_time', None)
            
            if doc_id not in doctor_stats:
                # If they did a consult but no billing today? Unlikely but possible
                doctor_stats[doc_id] = {"doctor_name": doc_id, "op_count": 0, "ip_count": 0, "consult_mins": 0, "patients": set()}

            if c_start and c_end:
                try:
                    if isinstance(c_start, str): c_start = datetime.fromisoformat(c_start.replace('Z', '+00:00'))
                    if isinstance(c_end, str): c_end = datetime.fromisoformat(c_end.replace('Z', '+00:00'))
                    duration_mins = int((c_end - c_start).total_seconds() / 60)
                    if duration_mins > 0:
                        doctor_stats[doc_id]["consult_mins"] += duration_mins
                except:
                    pass

        # Convert to list
        from hospital.Views.dbcollection import get_employee_name_by_id
        
        doctor_metrics = []
        for doc_id, stats in doctor_stats.items():
            actual_name = get_employee_name_by_id(doc_id)
            if actual_name == "Unknown":
                actual_name = stats["doctor_name"] # fallback if not found in dbcollection

            # Convert sets to comma separated string
            pat_str = ", ".join(list(stats["patients"]))
            doctor_metrics.append({
                "doctor_name": actual_name,
                "op_count": stats["op_count"],
                "ip_count": stats["ip_count"],
                "consult_mins": stats["consult_mins"],
                "patients_list": pat_str
            })

        # Sort by op_count descending
        doctor_metrics.sort(key=lambda x: x["op_count"], reverse=True)

        return Response({
            "success": True,
            "summary": summary,
            "peak_hour_data": peak_hour_data,
            "doctor_metrics": doctor_metrics
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)




@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_get_Doctor_patient(request):
    """
    Get patient details for paid billed patients only using Django ORM Billing and Patient models.
    Filters billing records where doctor_id matches the logged-in doctor's employee_id.
    """
    try:
        from django.db.models import Q

        data = request.data
        employee_id = data.get("auth-user-id")
        print("employee_id:", employee_id)

        paid_bills = Billing.objects.filter(payment_status__in=['Paid', 'paid', 'Pending', 'pending', 'Unpaid', 'unpaid']).select_related('patient').order_by('-billed_date')

        if employee_id:
            emp_str = str(employee_id).strip()
            doctor_queries = Q(doctor_id__iexact=emp_str) | Q(doctor_id=emp_str)
            if emp_str.isdigit():
                doctor_queries |= Q(doctor_id=str(int(emp_str)))
            paid_bills = paid_bills.filter(doctor_queries)
        else:
            return Response([], status=status.HTTP_200_OK)


        result = []
        for bill in paid_bills:
            patient_obj = getattr(bill, 'patient', None)
            if not patient_obj:
                continue

            salutation = getattr(patient_obj, 'salutation', '') or ''
            first_name = getattr(patient_obj, 'firstName', '') or ''
            last_name = getattr(patient_obj, 'lastName', '') or ''
            full_name = f"{salutation} {first_name} {last_name}".strip()

            doctor_id = getattr(bill, 'doctor_id', '') or ''
            from hospital.Views.dbcollection import get_employee_name_by_id
            doctor_name = get_employee_name_by_id(doctor_id)

            patient_data = {
                "id": getattr(patient_obj, 'id', None),
                "uhid": getattr(patient_obj, 'uhid', '') or '',
                "salutation": salutation,
                "firstName": first_name,
                "lastName": last_name,
                "patient_name": full_name or f"Patient ({getattr(patient_obj, 'uhid', '')})",
                "age": getattr(patient_obj, 'age', None),
                "gender": getattr(patient_obj, 'gender', '') or '',
                "dob": str(patient_obj.dob) if getattr(patient_obj, 'dob', None) else '',
                "mobilePhone": getattr(patient_obj, 'mobilePhone', '') or '',
                "blood_group": getattr(patient_obj, 'blood_group', '') or '',
                "city": getattr(patient_obj, 'city', '') or '',
                "permanent_address": getattr(patient_obj, 'permanent_address', '') or '',
                "doctorName": doctor_name,
                "emergency_contact": getattr(patient_obj, 'emergency_contact', '') or '',
            }

            billed_d = getattr(bill, 'billed_date', None)
            billed_date_str = billed_d.isoformat() if billed_d else ""

            latest_vital = None
            is_completed_today = False
            uhid_str = patient_data.get("uhid")
            if uhid_str:
                vital_entries = list(VitalEntry.objects.filter(uhid=uhid_str).order_by('-created_date')[:1])
                vital_entry_obj = vital_entries[0] if vital_entries else None
                if vital_entry_obj:
                    latest_vital = VitalEntrySerializer(vital_entry_obj).data
                    
                    if getattr(vital_entry_obj, 'created_date', None):
                        from django.utils import timezone
                        if vital_entry_obj.created_date.date() == timezone.now().date():
                            is_completed_today = True

            result.append({
                "bill_number": getattr(bill, 'bill_number', ''),
                "billed_date": billed_date_str,
                "payment_status": getattr(bill, 'payment_status', 'Paid'),
                "total_fees": safe_float(getattr(bill, 'total_fees', None)),
                "registration_fee": safe_float(getattr(bill, 'registration_fee', None)),
                "consulting_fee": safe_float(getattr(bill, 'consulting_fee', None)),
                "payment_method": getattr(bill, 'payment_method', '') or '',
                "doctor_id": getattr(bill, 'doctor_id', '') or '',
                "patient": patient_data,
                "vital_entry": latest_vital,
                "vital_status": "Completed" if is_completed_today else "Pending"
            })

        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

