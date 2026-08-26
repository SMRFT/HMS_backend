import os
from pymongo import MongoClient
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from bson import Decimal128
from hospital.models import Patient
from .models import VitalEntry
from .serializer import VitalEntrySerializer


# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission, HasRolePermission
from rest_framework.decorators import api_view, permission_classes



def get_db():
    mongo_host = os.getenv('GLOBAL_DB_HOST') or 'mongodb://localhost:27017/'
    db_name = (os.getenv('HMS_DB_NAME') or 'HMS').strip()
    client = MongoClient(mongo_host)
    return client[db_name]


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
    Get patient details for paid billed patients only.
    Compares Billing.patient_id with Patient collection/model data to fetch patient details (including UHID),
    along with any recorded VitalEntry data.
    """
    try:
        db = get_db()
        billing_coll = db['hospital_billing']
        patient_coll = db['hospital_patient']

        # Query paid bills from hospital_billing collection sorted by billed_date descending
        raw_billings = list(billing_coll.find({
            "payment_status": {"$regex": "^paid$", "$options": "i"}
        }).sort("billed_date", -1))

        result = []
        for bill in raw_billings:
            pay_status = bill.get("payment_status", "Pending")
            if not pay_status or str(pay_status).strip().lower() != "paid":
                continue

            raw_pid = bill.get("patient_id")
            patient_doc = None

            # 1. Direct PyMongo $or lookup in hospital_patient collection by id (int/str) or uhid
            if raw_pid is not None:
                or_clauses = [{"id": raw_pid}, {"id": str(raw_pid)}]
                try:
                    or_clauses.append({"id": int(raw_pid)})
                except (ValueError, TypeError):
                    pass
                or_clauses.append({"uhid": str(raw_pid)})
                patient_doc = patient_coll.find_one({"$or": or_clauses})

            if not patient_doc:
                uhid_val = bill.get("uhid") or bill.get("patient_uhid")
                if uhid_val:
                    patient_doc = patient_coll.find_one({"uhid": str(uhid_val)})

            patient_data = {}
            if patient_doc:
                salutation = patient_doc.get("salutation", "") or ""
                first_name = patient_doc.get("firstName", "") or ""
                last_name = patient_doc.get("lastName", "") or ""
                full_name = f"{salutation} {first_name} {last_name}".strip()

                patient_data = {
                    "id": patient_doc.get("id") or raw_pid,
                    "uhid": patient_doc.get("uhid", "") or "",
                    "salutation": salutation,
                    "firstName": first_name,
                    "lastName": last_name,
                    "patient_name": full_name or f"Patient #{patient_doc.get('id', raw_pid)}",
                    "age": patient_doc.get("age", ""),
                    "gender": patient_doc.get("gender", ""),
                    "dob": str(patient_doc.get("dob", "")) if patient_doc.get("dob") else "",
                    "mobilePhone": patient_doc.get("mobilePhone", "") or patient_doc.get("mobile", "") or "",
                    "blood_group": patient_doc.get("blood_group", "") or "",
                    "city": patient_doc.get("city", "") or "",
                    "permanent_address": patient_doc.get("permanent_address", "") or "",
                    "doctorName": patient_doc.get("doctorName", "") or "",
                    "emergency_contact": patient_doc.get("emergency_contact", "") or "",
                }
            else:
                # 2. Django ORM Fallback
                orm_patient = None
                if raw_pid is not None:
                    try:
                        orm_patient = Patient.objects.filter(id=raw_pid).first()
                        if not orm_patient and str(raw_pid).isdigit():
                            orm_patient = Patient.objects.filter(id=int(raw_pid)).first()
                        if not orm_patient:
                            orm_patient = Patient.objects.filter(uhid=str(raw_pid)).first()
                    except Exception:
                        pass

                if orm_patient:
                    salutation = orm_patient.salutation or ""
                    first_name = orm_patient.firstName or ""
                    last_name = orm_patient.lastName or ""
                    full_name = f"{salutation} {first_name} {last_name}".strip()
                    patient_data = {
                        "id": orm_patient.id,
                        "uhid": orm_patient.uhid or "",
                        "salutation": salutation,
                        "firstName": first_name,
                        "lastName": last_name,
                        "patient_name": full_name or f"Patient #{orm_patient.id}",
                        "age": orm_patient.age,
                        "gender": orm_patient.gender,
                        "dob": str(orm_patient.dob) if orm_patient.dob else "",
                        "mobilePhone": orm_patient.mobilePhone or "",
                        "blood_group": orm_patient.blood_group or "",
                        "city": orm_patient.city or "",
                        "permanent_address": orm_patient.permanent_address or "",
                        "doctorName": orm_patient.doctorName or "",
                        "emergency_contact": orm_patient.emergency_contact or "",
                    }
                else:
                    patient_data = {
                        "id": raw_pid,
                        "uhid": bill.get("uhid", "") or bill.get("patient_uhid", "") or "",
                        "patient_name": bill.get("patient_name", "") or "",
                        "mobilePhone": bill.get("mobilePhone", "") or bill.get("mobile", "") or "",
                        "doctorName": bill.get("doctorName", "") or bill.get("doctor_name", "") or "",
                    }

            latest_vital = None
            uhid = patient_data.get("uhid")
            if uhid:
                vital_entry_obj = VitalEntry.objects.filter(uhid=uhid).order_by('-created_date').first()
                if vital_entry_obj:
                    latest_vital = VitalEntrySerializer(vital_entry_obj).data

            billed_d = bill.get("billed_date") or bill.get("created_date")
            billed_date_str = str(billed_d) if billed_d else None

            result.append({
                "bill_number": bill.get("bill_number"),
                "billed_date": billed_date_str,
                "payment_status": pay_status,
                "total_fees": safe_float(bill.get("total_fees")),
                "registration_fee": safe_float(bill.get("registration_fee")),
                "consulting_fee": safe_float(bill.get("consulting_fee")),
                "payment_method": bill.get("payment_method"),
                "doctor_id": bill.get("doctor_id"),
                "patient": patient_data,
                "vital_entry": latest_vital,
                "vital_status": "Completed" if latest_vital else "Pending"
            })

        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_VitalEntry(request):
    """
    GET: Retrieve list of VitalEntry records (optionally filtered by ?uhid=...)
    POST: Create a new VitalEntry record using VitalEntrySerializer
    """
    if request.method == 'GET':
        uhid = request.query_params.get('uhid')
        if uhid:
            vitals = VitalEntry.objects.filter(uhid=uhid).order_by('-created_date')
        else:
            vitals = VitalEntry.objects.all().order_by('-created_date')
        serializer = VitalEntrySerializer(vitals, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        serializer = VitalEntrySerializer(data=request.data)
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
