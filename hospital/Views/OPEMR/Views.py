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
        # Query all paid bills via Django ORM Billing model (no auth-user-id filtering)
        paid_bills = Billing.objects.filter(payment_status__iexact="paid").select_related('patient').order_by('-billed_date')

        result = []
        for bill in paid_bills:
            patient_obj = getattr(bill, 'patient', None)
            if not patient_obj:
                continue

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
            payment_status__iexact="paid",
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
# @permission_classes([HasRoleAndDataPermission])
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
                "patient_name": data.get("patient_name", ""),
                "doctor_id": data.get("doctor_id", ""),
                "doctor_name": data.get("doctor_name", ""),
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
                "followup_date": data.get("followup_date", None)
            }

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
