import os
import re
import json
from datetime import datetime, timedelta
from bson import Decimal128, ObjectId
from pymongo import MongoClient
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny

from .models import IPDoctorNotes, IPNursingNotes
from .serializer import IPDoctorNotesSerializer, IPNursingNotesSerializer, to_plain_json

# Database Connections
MONGO_URI = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(MONGO_URI) if MONGO_URI else None
mongo_db = client["HMS"] if client else None
global_db = client["Global"] if client else None
diagnostics_db = client["Diagnostics"] if client else None
profile_collection = global_db["backend_diagnostics_profile"] if global_db is not None else None


def serialize_value(val):
    if isinstance(val, (datetime,)):
        return val.isoformat()
    if isinstance(val, (ObjectId,)):
        return str(val)
    if isinstance(val, (Decimal128,)):
        return float(val.to_decimal())
    return val


def serialize_dict(d):
    if isinstance(d, list):
        return [serialize_dict(item) for item in d]
    if isinstance(d, dict):
        return {k: serialize_dict(v) for k, v in d.items()}
    return serialize_value(d)


def resolve_doctor_id_and_name(identifier):
    """
    Given an identifier which could be employeeId, doctor_id, auth-user-id, or employeeName,
    matches against profile_collection (backend_diagnostics_profile) and returns (doctor_id, doctor_name).
    Never stores degrees or long name strings into doctor_id.
    """
    if not identifier:
        return "", ""
    ident_str = str(identifier).strip()
    if not ident_str:
        return "", ""

    if profile_collection is not None:
        # Exact search by employeeId or employeeName
        queries = [
            {"employeeId": ident_str},
            {"employeeName": ident_str},
            {"employeeName": {"$regex": f"^{re.escape(ident_str)}$", "$options": "i"}}
        ]
        if ident_str.isdigit():
            queries.append({"employeeId": int(ident_str)})

        doc_obj = profile_collection.find_one({"$or": queries}, {"employeeId": 1, "employeeName": 1, "department": 1, "_id": 0})
        if doc_obj:
            emp_id = str(doc_obj.get("employeeId") or ident_str)
            emp_name = doc_obj.get("employeeName") or ident_str
            return emp_id, emp_name

        # Fuzzy search if ident_str contains degrees/qualifications (e.g. "Najma B., MS., DNB.")
        base_name = ident_str.split(",")[0].replace("Dr.", "").replace("Dr ", "").strip()
        if base_name:
            doc_obj = profile_collection.find_one(
                {"employeeName": {"$regex": re.escape(base_name), "$options": "i"}},
                {"employeeId": 1, "employeeName": 1, "department": 1, "_id": 0}
            )
            if doc_obj:
                emp_id = str(doc_obj.get("employeeId") or ident_str)
                emp_name = doc_obj.get("employeeName") or ident_str
                return emp_id, emp_name

    return ident_str, ident_str


def extract_admission_room_bed(adm):
    """
    Safely extracts current active or latest room_no, bed_no, and ward/block name
    from hospital_admission document across all room structure schemas.
    """
    if not isinstance(adm, dict):
        return "", "", ""
    room_no = adm.get("roomNo") or adm.get("room_no") or adm.get("room") or ""
    bed_no = adm.get("bedNo") or adm.get("bed_no") or adm.get("bed") or ""
    block_name = adm.get("blockName") or adm.get("ward") or adm.get("wardName") or ""

    for field in ["room_details", "roomShiftingDetails", "roomShitingDetails"]:
        shift_arr = adm.get(field, [])
        if isinstance(shift_arr, list) and len(shift_arr) > 0:
            for entry in shift_arr:
                if isinstance(entry, dict):
                    is_active = (
                        entry.get("is_roomActive") is True or
                        str(entry.get("status")).lower() == "active" or
                        entry.get("endDateTime") in [None, ""] or
                        entry.get("is_active") is True
                    )
                    if is_active:
                        room_no = entry.get("roomNo") or entry.get("room_no") or room_no
                        bed_no = entry.get("bedNo") or entry.get("bed_no") or bed_no
                        block_name = entry.get("blockName") or entry.get("ward") or block_name
                        return str(room_no or ""), str(bed_no or ""), str(block_name or "")
                    elif not room_no:
                        room_no = entry.get("roomNo") or entry.get("room_no") or room_no
                        bed_no = entry.get("bedNo") or entry.get("bed_no") or bed_no
                        block_name = entry.get("blockName") or entry.get("ward") or block_name

    return str(room_no or ""), str(bed_no or ""), str(block_name or "")


def enrich_note_dict(note_dict):
    """
    Enriches doctor note dictionary with patient demographics, admission details,
    and doctor display name from Profile collection.
    """
    if not note_dict:
        return note_dict

    uhid = note_dict.get("uhid")
    ip_number = note_dict.get("ip_number")
    raw_doctor_id = note_dict.get("doctor_id")

    # Doctor name resolution from profile collection
    clean_doc_id, resolved_doc_name = resolve_doctor_id_and_name(raw_doctor_id)
    note_dict["doctor_id"] = clean_doc_id
    note_dict["doctor_name"] = resolved_doc_name or clean_doc_id or "Attending Physician"

    # Patient demographics from Patient collection
    if uhid and mongo_db is not None:
        patient_doc = mongo_db["hospital_patient"].find_one({"uhid": uhid})
        if patient_doc:
            salutation = patient_doc.get("salutation", "") or ""
            fname = patient_doc.get("firstName", "") or ""
            lname = patient_doc.get("lastName", "") or ""
            note_dict["patient_name"] = f"{salutation} {fname} {lname}".strip()
            note_dict["age"] = patient_doc.get("age")
            note_dict["gender"] = patient_doc.get("gender", "") or ""

    # Admission & Room details from Admission collection
    if ip_number and mongo_db is not None:
        adm = mongo_db["hospital_admission"].find_one({"ipNumber": ip_number}) or mongo_db["hospital_admission"].find_one({"ip_number": ip_number})
        if adm:
            room_no, bed_no, block_name = extract_admission_room_bed(adm)
            note_dict["room_no"] = room_no
            note_dict["bed_no"] = bed_no
            note_dict["ward_name"] = block_name

            if not note_dict.get("patient_name"):
                sal = adm.get("salutation", "") or ""
                fn = adm.get("firstName", "") or ""
                ln = adm.get("lastName", "") or ""
                p_name = f"{sal} {fn} {ln}".strip() or adm.get("patientName", "")
                note_dict["patient_name"] = p_name or f"Patient ({ip_number})"

            if not note_dict.get("age"):
                note_dict["age"] = adm.get("age")
            if not note_dict.get("gender"):
                note_dict["gender"] = adm.get("gender", "")

    # Clean all JSON dict and list fields
    json_dict_fields = ['allergies', 'past_history', 'social_history', 'menstrual_history',
                        'vaccination_history', 'obstetrics_history', 'investigations_done',
                        'physical_examination', 'provisional_diagnosis', 'plan_of_care']
    for f in json_dict_fields:
        if f in note_dict:
            note_dict[f] = to_plain_json(note_dict[f], dict)

    json_list_fields = ['chief_complaints', 'present_medications']
    for f in json_list_fields:
        if f in note_dict:
            note_dict[f] = to_plain_json(note_dict[f], list)

    return note_dict


@api_view(['GET'])
@permission_classes([AllowAny])
def IPEMR_get_admitted_patients(request):
    """
    Returns list of admitted IP patients with enriched patient, room, doctor,
    and IP doctor note history information.
    """
    try:
        query = {
            "is_admitted": True,
            "is_cancelled": {"$ne": True},
            "is_discharged": {"$ne": True}
        }

        doctor_filter = request.GET.get("doctor", "").strip()
        search_query = request.GET.get("search", "").strip()

        if mongo_db is not None:
            raw_admissions = list(mongo_db["hospital_admission"].find(query).sort("admissionDateTime", -1))
        else:
            raw_admissions = []

        patient_list = []

        for adm in raw_admissions:
            ip_number = str(adm.get("ipNumber", "") or "")
            uhid = str(adm.get("uhid", "") or "")
            if not ip_number and not uhid:
                continue

            # Patient details enrichment
            patient_name = ""
            age = adm.get("age")
            gender = adm.get("gender") or adm.get("Gender") or ""
            mobile = adm.get("mobile") or adm.get("phone") or adm.get("mobilePhone") or ""
            blood_group = adm.get("blood_group") or adm.get("bloodGroup") or adm.get("BloodGroup") or ""

            patient_doc = None
            if uhid and mongo_db is not None:
                uhid_clean = str(uhid).strip()
                uhid_pattern = re.sub(r'/0+', r'/0*', uhid_clean)
                patient_doc = mongo_db["hospital_patient"].find_one({
                    "$or": [
                        {"uhid": uhid_clean},
                        {"uhid": {"$regex": f"^{re.escape(uhid_clean)}$", "$options": "i"}},
                        {"uhid": {"$regex": f"^{uhid_pattern}$", "$options": "i"}}
                    ]
                })

            if patient_doc:
                salutation = patient_doc.get("salutation", "") or ""
                fname = patient_doc.get("firstName", "") or ""
                lname = patient_doc.get("lastName", "") or ""
                patient_name = f"{salutation} {fname} {lname}".strip()
                if not age:
                    age = patient_doc.get("age")
                gender = patient_doc.get("gender") or patient_doc.get("Gender") or gender
                mobile = patient_doc.get("mobilePhone") or patient_doc.get("mobile") or mobile
                blood_group = (
                    patient_doc.get("blood_group") or patient_doc.get("bloodGroup") or
                    patient_doc.get("BloodGroup") or patient_doc.get("blood_type") or blood_group
                )

            if not patient_name:
                sal = adm.get("salutation", "") or ""
                fn = adm.get("firstName", "") or ""
                ln = adm.get("lastName", "") or ""
                patient_name = f"{sal} {fn} {ln}".strip() or adm.get("patientName", "") or f"Patient ({uhid or ip_number})"

            # Doctor details: match with profile and resolve clean doctor_id & name
            admitting_doc_raw = adm.get("admittingDoctor", "")
            consulting_doc_raw = adm.get("consultingDoctor", "")
            raw_doc_ident = admitting_doc_raw or consulting_doc_raw or ""

            clean_doc_id, resolved_doc_name = resolve_doctor_id_and_name(raw_doc_ident)

            # Room & Bed details
            room_no, bed_no, block_name = extract_admission_room_bed(adm)

            # Check if doctor filter applies
            if doctor_filter and doctor_filter.lower() not in resolved_doc_name.lower() and doctor_filter.lower() not in clean_doc_id.lower():
                continue

            # Check search query
            if search_query:
                q_lower = search_query.lower()
                matches = (
                    q_lower in patient_name.lower() or
                    q_lower in uhid.lower() or
                    q_lower in ip_number.lower() or
                    q_lower in str(room_no).lower() or
                    q_lower in str(bed_no).lower() or
                    q_lower in resolved_doc_name.lower() or
                    q_lower in clean_doc_id.lower()
                )
                if not matches:
                    continue

            # Doctor notes count & latest note
            note_count = 0
            latest_note = None
            try:
                notes_qs = IPDoctorNotes.objects.filter(ip_number=ip_number).order_by('-note_date')
                note_count = notes_qs.count()
                if note_count > 0:
                    first_note = notes_qs.first()
                    _, note_doc_name = resolve_doctor_id_and_name(first_note.doctor_id)
                    latest_note = {
                        "id": str(getattr(first_note, '_id', first_note.id)),
                        "note_type": first_note.note_type,
                        "note_date": first_note.note_date.isoformat() if first_note.note_date else "",
                        "doctor_id": first_note.doctor_id,
                        "doctor_name": note_doc_name or resolved_doc_name or first_note.doctor_id,
                        "is_finalized": first_note.is_finalized
                    }
            except Exception:
                pass

            adm_date = adm.get("admissionDateTime")
            adm_date_str = adm_date.isoformat() if isinstance(adm_date, datetime) else str(adm_date or "")

            patient_list.append({
                "id": str(adm.get("_id", "")),
                "ip_number": ip_number,
                "uhid": uhid,
                "patient_name": patient_name,
                "age": age,
                "gender": gender,
                "mobile": mobile,
                "blood_group": blood_group,
                "room_no": room_no,
                "bed_no": bed_no,
                "block_name": block_name,
                "doctor_id": clean_doc_id,
                "doctor_name": resolved_doc_name or clean_doc_id,
                "admission_date": adm_date_str,
                "insurance": adm.get("insurance_company", "") or adm.get("customer_type", "General"),
                "ward_status": adm.get("ward_status", "Admitted"),
                "note_count": note_count,
                "latest_note": latest_note
            })

        return Response({"status": "success", "count": len(patient_list), "data": patient_list}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def IPEMR_DoctorNotes(request):
    """
    GET: List doctor notes for a patient by ?ip_number=... or ?uhid=...
    POST: Create a new IP Doctor Note or update existing note
    """
    if request.method == 'GET':
        try:
            ip_number = request.GET.get("ip_number", "").strip()
            uhid = request.GET.get("uhid", "").strip()
            raw_doctor_id = request.GET.get("doctor_id", "").strip()

            qs = IPDoctorNotes.objects.all()

            if ip_number:
                qs = qs.filter(ip_number=ip_number)
            elif uhid:
                qs = qs.filter(uhid=uhid)

            if raw_doctor_id:
                clean_id, _ = resolve_doctor_id_and_name(raw_doctor_id)
                qs = qs.filter(doctor_id=clean_id)

            qs = qs.order_by('-note_date')
            serialized_data = IPDoctorNotesSerializer(qs, many=True).data

            # Enrich each note with dynamic patient and doctor details
            enriched_notes = [enrich_note_dict(note) for note in serialized_data]
            return Response({"status": "success", "count": len(enriched_notes), "data": enriched_notes}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    elif request.method == 'POST':
        try:
            data = request.data.copy()
            note_id = data.get("id")

            # 1. Who is entering notes: get from auth-user-id header / data
            auth_user_id = (
                request.headers.get("auth-user-id") or
                data.get("auth-user-id") or
                request.headers.get("employee-id") or
                data.get("employee_id") or
                ""
            )

            # Doctor passed in payload or selected patient
            specified_doc = data.get("doctor_id") or data.get("admitting_doctor") or ""

            # Match with profile and resolve clean doctor_id (employeeId)
            # Priority: Auth User ID entering the notes -> then specified doctor
            author_doc_id, _ = resolve_doctor_id_and_name(auth_user_id) if auth_user_id else ("", "")
            specified_clean_id, _ = resolve_doctor_id_and_name(specified_doc) if specified_doc else ("", "")

            final_doctor_id = author_doc_id or specified_clean_id or str(auth_user_id or specified_doc or "")
            data["doctor_id"] = str(final_doctor_id)

            # 2. Audit fields
            branch_code = (
                request.headers.get("auth-branch-code") or
                data.get("auth-branch-code") or
                data.get("branch_code") or
                ""
            )

            outlet_code = (
                request.headers.get("auth-outlet-code") or
                data.get("auth-outlet-code") or
                data.get("outlet_code") or
                ""
            )

            hospital_code = (
                request.headers.get("auth-hospital-code") or
                data.get("auth-hospital-code") or
                data.get("hospital_code") or
                ""
            )

            if not note_id:
                data["created_by"] = str(auth_user_id or final_doctor_id)
                data["created_date"] = timezone.now()
            data["lastmodified_by"] = str(auth_user_id or final_doctor_id)
            data["branch_code"] = branch_code
            data["outlet_code"] = outlet_code
            data["hospital_code"] = hospital_code

            # Remove redundant demographic fields if present in incoming payload
            for redundant_field in ["patient_name", "age", "gender", "room_no", "bed_no", "ward_name", "doctor_name"]:
                data.pop(redundant_field, None)

            if note_id:
                try:
                    obj_id = ObjectId(str(note_id)) if ObjectId.is_valid(str(note_id)) else note_id
                    instance = IPDoctorNotes.objects.get(_id=obj_id)
                    serializer = IPDoctorNotesSerializer(instance, data=data, partial=True)
                except (IPDoctorNotes.DoesNotExist, Exception):
                    return Response({"status": "error", "message": "Doctor Note not found."}, status=status.HTTP_404_NOT_FOUND)
            else:
                serializer = IPDoctorNotesSerializer(data=data)

            if serializer.is_valid():
                saved_obj = serializer.save()
                saved_data = enrich_note_dict(IPDoctorNotesSerializer(saved_obj).data)
                return Response({
                    "status": "success",
                    "message": "Doctor note saved successfully.",
                    "data": saved_data
                }, status=status.HTTP_201_CREATED if not note_id else status.HTTP_200_OK)
            else:
                return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
def IPEMR_DoctorNotes_detail(request, note_id):
    """
    GET, UPDATE or DELETE a single doctor note by ID.
    """
    try:
        obj_id = ObjectId(str(note_id)) if ObjectId.is_valid(str(note_id)) else note_id
        instance = IPDoctorNotes.objects.get(_id=obj_id)
    except (IPDoctorNotes.DoesNotExist, Exception):
        return Response({"status": "error", "message": "Doctor Note not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = IPDoctorNotesSerializer(instance)
        return Response({"status": "success", "data": enrich_note_dict(serializer.data)}, status=status.HTTP_200_OK)

    elif request.method in ['PUT', 'PATCH']:
        data = request.data.copy()
        user_id = request.headers.get("auth-user-id") or data.get("auth-user-id") or data.get("employee_id") or ""
        data["lastmodified_by"] = user_id
        for redundant_field in ["patient_name", "age", "gender", "room_no", "bed_no", "ward_name", "doctor_name"]:
            data.pop(redundant_field, None)

        serializer = IPDoctorNotesSerializer(instance, data=data, partial=True)
        if serializer.is_valid():
            saved_obj = serializer.save()
            return Response({"status": "success", "message": "Doctor note updated successfully.", "data": enrich_note_dict(IPDoctorNotesSerializer(saved_obj).data)}, status=status.HTTP_200_OK)
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        try:
            instance.delete()
            return Response({"status": "success", "message": "Doctor note deleted successfully."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def IPEMR_get_patient_summary(request):
    """
    Returns full summary for an IP patient including admission details, previous doctor notes, and vitals.
    """
    try:
        ip_number = request.GET.get("ip_number", "").strip()
        uhid = request.GET.get("uhid", "").strip()

        if not ip_number and not uhid:
            return Response({"status": "error", "message": "Please provide ip_number or uhid."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Admission details
        adm_data = None
        if mongo_db is not None:
            q = {"ipNumber": ip_number} if ip_number else {"uhid": uhid}
            raw_adm = mongo_db["hospital_admission"].find_one(q)
            if raw_adm:
                adm_data = serialize_dict(raw_adm)

        # 2. Patient details
        patient_data = None
        target_uhid = uhid or (adm_data.get("uhid") if adm_data else "")
        if target_uhid and mongo_db is not None:
            raw_pat = mongo_db["hospital_patient"].find_one({"uhid": target_uhid})
            if raw_pat:
                patient_data = serialize_dict(raw_pat)

        # 3. Doctor Notes History
        notes_qs = IPDoctorNotes.objects.all()
        if ip_number:
            notes_qs = notes_qs.filter(ip_number=ip_number)
        elif target_uhid:
            notes_qs = notes_qs.filter(uhid=target_uhid)

        raw_notes = IPDoctorNotesSerializer(notes_qs.order_by('-note_date'), many=True).data
        notes_data = [enrich_note_dict(n) for n in raw_notes]

        # 4. Nursing Notes History
        nurse_qs = IPNursingNotes.objects.all()
        if ip_number:
            nurse_qs = nurse_qs.filter(ip_number=ip_number)
        elif target_uhid:
            nurse_qs = nurse_qs.filter(uhid=target_uhid)

        raw_nurse_notes = IPNursingNotesSerializer(nurse_qs.order_by('-note_date'), many=True).data
        nurse_notes_data = [enrich_nursing_note_dict(n) for n in raw_nurse_notes]

        return Response({
            "status": "success",
            "admission": adm_data,
            "patient": patient_data,
            "notes": notes_data,
            "nursing_notes": nurse_notes_data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def get_pain_severity_label(score):
    try:
        val = int(score)
    except (ValueError, TypeError):
        return "No Pain"
    if val <= 0:
        return "No Pain"
    elif val in [1, 2]:
        return "Mild Pain"
    elif val in [3, 4]:
        return "Moderate Pain"
    elif val in [5, 6]:
        return "Severe Pain"
    elif val in [7, 8]:
        return "Very Severe Pain"
    else:
        return "Worst Possible Pain"


def enrich_nursing_note_dict(note_dict):
    """
    Enriches nursing note dictionary with patient demographics, admission details,
    and nurse display name from Profile collection.
    """
    if not note_dict:
        return note_dict

    uhid = note_dict.get("uhid")
    ip_number = note_dict.get("ip_number")
    raw_nurse_id = note_dict.get("nurse_id")

    # Nurse name resolution from profile collection
    clean_nurse_id, resolved_nurse_name = resolve_doctor_id_and_name(raw_nurse_id)
    note_dict["nurse_id"] = clean_nurse_id
    note_dict["nurse_name"] = resolved_nurse_name or "Staff Nurse"

    # Ensure pain severity text matches score
    pain_sc = note_dict.get("pain_score", 0)
    note_dict["pain_severity"] = get_pain_severity_label(pain_sc)

    # Patient demographics from Patient collection
    if uhid and mongo_db is not None:
        patient_doc = mongo_db["hospital_patient"].find_one({"uhid": uhid})
        if patient_doc:
            salutation = patient_doc.get("salutation", "") or ""
            fname = patient_doc.get("firstName", "") or ""
            lname = patient_doc.get("lastName", "") or ""
            note_dict["patient_name"] = f"{salutation} {fname} {lname}".strip()
            note_dict["age"] = patient_doc.get("age")
            note_dict["gender"] = patient_doc.get("gender", "") or ""

    # Admission & Room details from Admission collection
    if ip_number and mongo_db is not None:
        adm = mongo_db["hospital_admission"].find_one({"ipNumber": ip_number}) or mongo_db["hospital_admission"].find_one({"ip_number": ip_number})
        if adm:
            room_no, bed_no, block_name = extract_admission_room_bed(adm)
            note_dict["room_no"] = room_no
            note_dict["bed_no"] = bed_no
            note_dict["ward_name"] = block_name

            if not note_dict.get("patient_name"):
                sal = adm.get("salutation", "") or ""
                fn = adm.get("firstName", "") or ""
                ln = adm.get("lastName", "") or ""
                note_dict["patient_name"] = f"{sal} {fn} {ln}".strip() or adm.get("patientName", "")

            if not note_dict.get("age"):
                note_dict["age"] = adm.get("age")
            if not note_dict.get("gender"):
                note_dict["gender"] = adm.get("gender", "")

    # Clean JSON fields
    json_fields = ['vitals', 'intake_output', 'nursing_assessment', 'nursing_interventions']
    for f in json_fields:
        if f in note_dict:
            note_dict[f] = to_plain_json(note_dict[f], dict)

    return note_dict


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def IPEMR_NursingNotes(request):
    """
    GET: List nursing notes for a patient by ?ip_number=... or ?uhid=...
    POST: Create a new IP Nursing Note or update existing note
    """
    if request.method == 'GET':
        try:
            ip_number = request.GET.get("ip_number", "").strip()
            uhid = request.GET.get("uhid", "").strip()
            nurse_id = request.GET.get("nurse_id", "").strip()

            qs = IPNursingNotes.objects.all()

            if ip_number:
                qs = qs.filter(ip_number=ip_number)
            elif uhid:
                qs = qs.filter(uhid=uhid)

            if nurse_id:
                clean_id, _ = resolve_doctor_id_and_name(nurse_id)
                qs = qs.filter(nurse_id=clean_id)

            qs = qs.order_by('-note_date')
            serialized_data = IPNursingNotesSerializer(qs, many=True).data

            enriched_notes = [enrich_nursing_note_dict(note) for note in serialized_data]
            return Response({"status": "success", "count": len(enriched_notes), "data": enriched_notes}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    elif request.method == 'POST':
        try:
            data = request.data.copy()
            note_id = data.get("id")

            # 1. Who is entering notes: get from auth-user-id header / data
            auth_user_id = (
                request.headers.get("auth-user-id") or
                data.get("auth-user-id") or
                request.headers.get("employee-id") or
                data.get("employee_id") or
                data.get("nurse_id") or
                ""
            )

            clean_nurse_id, _ = resolve_doctor_id_and_name(auth_user_id) if auth_user_id else ("", "")
            final_nurse_id = clean_nurse_id or str(auth_user_id or "")
            data["nurse_id"] = final_nurse_id

            # Calculate pain severity label based on numeric score
            raw_pain_score = data.get("pain_score", 0)
            try:
                pain_int = int(raw_pain_score)
            except (ValueError, TypeError):
                pain_int = 0
            data["pain_score"] = pain_int
            data["pain_severity"] = get_pain_severity_label(pain_int)

            # 2. Audit fields
            branch_code = (
                request.headers.get("auth-branch-code") or
                data.get("auth-branch-code") or
                data.get("branch_code") or
                ""
            )

            outlet_code = (
                request.headers.get("auth-outlet-code") or
                data.get("auth-outlet-code") or
                data.get("outlet_code") or
                ""
            )

            hospital_code = (
                request.headers.get("auth-hospital-code") or
                data.get("auth-hospital-code") or
                data.get("hospital_code") or
                ""
            )

            if not note_id:
                data["created_by"] = str(auth_user_id or final_nurse_id)
                data["created_date"] = timezone.now()
            data["lastmodified_by"] = str(auth_user_id or final_nurse_id)
            data["branch_code"] = branch_code
            data["outlet_code"] = outlet_code
            data["hospital_code"] = hospital_code

            # Remove redundant demographic fields if present
            for redundant_field in ["patient_name", "age", "gender", "room_no", "bed_no", "ward_name", "nurse_name"]:
                data.pop(redundant_field, None)

            if note_id:
                try:
                    obj_id = ObjectId(str(note_id)) if ObjectId.is_valid(str(note_id)) else note_id
                    instance = IPNursingNotes.objects.get(_id=obj_id)
                    serializer = IPNursingNotesSerializer(instance, data=data, partial=True)
                except (IPNursingNotes.DoesNotExist, Exception):
                    return Response({"status": "error", "message": "Nursing Note not found."}, status=status.HTTP_404_NOT_FOUND)
            else:
                serializer = IPNursingNotesSerializer(data=data)

            if serializer.is_valid():
                saved_obj = serializer.save()
                saved_data = enrich_nursing_note_dict(IPNursingNotesSerializer(saved_obj).data)
                return Response({
                    "status": "success",
                    "message": "Nursing note saved successfully.",
                    "data": saved_data
                }, status=status.HTTP_201_CREATED if not note_id else status.HTTP_200_OK)
            else:
                return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
def IPEMR_NursingNotes_detail(request, note_id):
    """
    GET, UPDATE or DELETE a single nursing note by ID.
    """
    try:
        obj_id = ObjectId(str(note_id)) if ObjectId.is_valid(str(note_id)) else note_id
        instance = IPNursingNotes.objects.get(_id=obj_id)
    except (IPNursingNotes.DoesNotExist, Exception):
        return Response({"status": "error", "message": "Nursing Note not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = IPNursingNotesSerializer(instance)
        return Response({"status": "success", "data": enrich_nursing_note_dict(serializer.data)}, status=status.HTTP_200_OK)

    elif request.method in ['PUT', 'PATCH']:
        data = request.data.copy()
        user_id = request.headers.get("auth-user-id") or data.get("auth-user-id") or data.get("employee_id") or ""
        data["lastmodified_by"] = user_id

        if "pain_score" in data:
            try:
                pain_int = int(data["pain_score"])
            except (ValueError, TypeError):
                pain_int = 0
            data["pain_score"] = pain_int
            data["pain_severity"] = get_pain_severity_label(pain_int)

        for redundant_field in ["patient_name", "age", "gender", "room_no", "bed_no", "ward_name", "nurse_name"]:
            data.pop(redundant_field, None)

        serializer = IPNursingNotesSerializer(instance, data=data, partial=True)
        if serializer.is_valid():
            saved_obj = serializer.save()
            return Response({"status": "success", "message": "Nursing note updated successfully.", "data": enrich_nursing_note_dict(IPNursingNotesSerializer(saved_obj).data)}, status=status.HTTP_200_OK)
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        try:
            instance.delete()
            return Response({"status": "success", "message": "Nursing note deleted successfully."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def IPEMR_patient_history(request):
    """
    Comprehensive Clinical Patient History (Doctor & Clinical View):
    Fetches full medical timeline for a patient without any financial or billing data.
    - Patient Demographics & Profile
    - Past & Current IP Admissions (with room/bed from room_details)
    - OP Registration & Consultation Visits
    - Detailed Diagnostic & Lab Investigation Results from `Diagnostics.core_testvalue`,
      `core_mbtestvalue`, and `core_testdetails`
    - Doctor Clinical Notes History
    - Bedside Nursing Notes & Vitals History
    - Past Hospital Discharge Summaries
    - Prescribed / Administered Medications History
    """
    try:
        uhid_query = request.GET.get('uhid', '').strip()
        ip_query = request.GET.get('ip_number', '').strip()
        search_query = request.GET.get('search', '').strip()

        lookup = uhid_query or ip_query or search_query
        if not lookup:
            return Response({
                "status": "error",
                "message": "Please provide a UHID, IP Number, or Patient Search term."
            }, status=status.HTTP_400_BAD_REQUEST)

        if mongo_db is None:
            return Response({"status": "error", "message": "Database connection unavailable."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        patient_coll = mongo_db["hospital_patient"]
        admission_coll = mongo_db["hospital_admission"]
        registration_coll = mongo_db["hospital_registration"]
        doctor_notes_coll = mongo_db["hospital_doctornotes"]
        nursing_notes_coll = mongo_db["hospital_nursingnotes"]
        summary_coll = mongo_db["hospital_summary"]
        pharmacy_coll = mongo_db["hospital_pharmacybilling"]
        pharm_item_coll = mongo_db["hospital_pharmacyitem"]
        invest_coll = mongo_db["hospital_investbilling"]

        # ── 1. Match Patient Document ──
        patient_doc = None
        matched_uhid = None

        if uhid_query:
            patient_doc = patient_coll.find_one({"uhid": {"$regex": f"^{re.escape(uhid_query)}$", "$options": "i"}})
            if not patient_doc:
                patient_doc = patient_coll.find_one({"uhid": {"$regex": re.escape(uhid_query), "$options": "i"}})
        elif ip_query:
            adm_doc = admission_coll.find_one({"$or": [{"ipNumber": ip_query}, {"ip_number": ip_query}]})
            if adm_doc:
                matched_uhid = adm_doc.get("uhid")
                patient_doc = patient_coll.find_one({"uhid": matched_uhid})
        elif search_query:
            patient_doc = patient_coll.find_one({
                "$or": [
                    {"uhid": {"$regex": re.escape(search_query), "$options": "i"}},
                    {"mobilePhone": {"$regex": re.escape(search_query), "$options": "i"}},
                    {"firstName": {"$regex": re.escape(search_query), "$options": "i"}},
                    {"lastName": {"$regex": re.escape(search_query), "$options": "i"}},
                ]
            })
            if not patient_doc:
                adm_doc = admission_coll.find_one({"$or": [{"ipNumber": search_query}, {"ip_number": search_query}]})
                if adm_doc:
                    matched_uhid = adm_doc.get("uhid")
                    patient_doc = patient_coll.find_one({"uhid": matched_uhid})

        if not patient_doc and not matched_uhid and (uhid_query or lookup):
            # Fallback numeric match
            parts_fallback = (uhid_query or lookup).split('/')
            num_fb = parts_fallback[-1].lstrip('0') or parts_fallback[-1]
            if len(num_fb) >= 2:
                patient_doc = patient_coll.find_one({"uhid": {"$regex": f"0*{re.escape(num_fb)}$", "$options": "i"}})

        uhid = patient_doc.get("uhid") if patient_doc else (matched_uhid or uhid_query or lookup)
        uhid_clean = uhid.strip() if uhid else ""

        # Normalize Patient Profile
        full_name = f"{patient_doc.get('salutation', '')} {patient_doc.get('firstName', '')} {patient_doc.get('lastName', '')}".strip() if patient_doc else "Patient"
        addr_parts = [
            patient_doc.get('permanent_address') or '',
            patient_doc.get('area') or '',
            patient_doc.get('city') or '',
            patient_doc.get('state') or ''
        ] if patient_doc else []
        full_address = ', '.join(p for p in addr_parts if p)

        patient_profile = {
            "uhid": uhid_clean,
            "patient_name": full_name or "Patient",
            "age": patient_doc.get("age", "") if patient_doc else "",
            "gender": patient_doc.get("gender", "") if patient_doc else "",
            "mobile": patient_doc.get("mobilePhone", "") if patient_doc else "",
            "blood_group": patient_doc.get("blood_group", "") if patient_doc else "",
            "address": full_address,
            "father_spouse": patient_doc.get("fatherOrSpouseName", "") if patient_doc else "",
            "created_date": serialize_value(patient_doc.get("created_date")) if patient_doc else ""
        }

        # Build flexible zero-padded regexes for UHID (e.g. S026/00551 vs S026/000551 vs 00551)
        parts = uhid_clean.split('/')
        prefix = parts[0] if len(parts) > 1 else ""
        suffix = parts[-1] if len(parts) > 1 else uhid_clean
        num_core = suffix.lstrip('0') or suffix

        uhid_patterns = [
            re.escape(uhid_clean),
            f"{prefix}/0*{num_core}$" if prefix else f"0*{num_core}$",
            f"0*{num_core}$"
        ]
        combined_uhid_regex = "|".join(filter(None, uhid_patterns))

        # ── 2. IP Admissions History ──
        admissions_query = {
            "$or": [
                {"uhid": {"$regex": combined_uhid_regex, "$options": "i"}},
                {"ipNumber": ip_query} if ip_query else {"uhid": {"$regex": combined_uhid_regex, "$options": "i"}},
                {"ip_number": ip_query} if ip_query else {"uhid": {"$regex": combined_uhid_regex, "$options": "i"}}
            ]
        }
        admissions_cursor = list(admission_coll.find(admissions_query))
        admissions = []
        all_ip_numbers = set([ip_query] if ip_query else [])

        for adm in admissions_cursor:
            ip_num = adm.get("ipNumber") or adm.get("ip_number") or ""
            if ip_num:
                all_ip_numbers.add(ip_num)

            doc_id = adm.get("admittingDoctor") or adm.get("doctor_id") or ""
            _, doc_name = resolve_doctor_id_and_name(doc_id)
            if not doc_name and isinstance(doc_id, str):
                doc_name = doc_id

            room_no = adm.get("roomNo") or adm.get("room_no") or ""
            bed_no = adm.get("bedNo") or adm.get("bed_no") or ""
            if not room_no and adm.get("room_details"):
                for rd in adm.get("room_details"):
                    if rd.get("is_roomActive") or not room_no:
                        room_no = rd.get("roomNo", "")
                        bed_no = rd.get("bedNo", "")

            adm_date = adm.get("admissionDateTime") or adm.get("admissionDate") or adm.get("created_date")
            dis_date = adm.get("dischargeDateTime") or adm.get("dischargeDate")

            admissions.append({
                "id": str(adm.get("_id")),
                "ip_number": ip_num,
                "admission_date": serialize_value(adm_date),
                "discharge_date": serialize_value(dis_date),
                "is_discharged": bool(adm.get("is_discharged") or dis_date),
                "room_no": room_no,
                "bed_no": bed_no,
                "ward_name": adm.get("wardName") or adm.get("ward_name") or "",
                "doctor_name": doc_name or "Attending Physician",
                "department": adm.get("department") or "",
                "reason_for_admission": adm.get("reasonForAdmission") or adm.get("chief_complaint") or "",
                "provisional_diagnosis": adm.get("provisionalDiagnosis") or "",
                "final_diagnosis": adm.get("finalDiagnosis") or "",
                "discharge_summary_status": adm.get("discharge_status") or ("Completed" if dis_date else "Active Stay")
            })

        # Sort admissions descending by date
        admissions.sort(key=lambda x: str(x.get("admission_date") or ""), reverse=True)

        # ── 3. OP Registration Visits ──
        op_visits_cursor = registration_coll.find({"uhid": {"$regex": combined_uhid_regex, "$options": "i"}}).limit(50)
        op_visits = []
        for reg in op_visits_cursor:
            doc_id = reg.get("doctor_id") or reg.get("consultant") or ""
            _, doc_name = resolve_doctor_id_and_name(doc_id)
            op_visits.append({
                "id": str(reg.get("_id")),
                "registration_date": serialize_value(reg.get("registrationDate") or reg.get("created_date")),
                "op_number": reg.get("opNumber") or reg.get("op_number") or "",
                "token_number": reg.get("tokenNumber") or reg.get("token") or "",
                "doctor_name": doc_name or reg.get("consultant") or "Consultant",
                "department": reg.get("department") or "",
                "visit_type": reg.get("visitType") or "Consultation",
                "chief_complaint": reg.get("chief_complaint") or reg.get("reason") or ""
            })
        op_visits.sort(key=lambda x: str(x.get("registration_date") or ""), reverse=True)

        # ── 4. Detailed Diagnostics & Lab Investigation Results (core_testvalue & core_testdetails) ──
        lab_results = []
        if diagnostics_db is not None:
            core_hmsbarcode = diagnostics_db["core_hmsbarcode"]
            core_testvalue = diagnostics_db["core_testvalue"]
            core_mbtestvalue = diagnostics_db["core_mbtestvalue"]
            core_testdetails = diagnostics_db["core_testdetails"]

            # Match barcodes by UHID patterns, IP numbers, or Bill numbers
            barcode_query = [
                {"patient_id": {"$regex": combined_uhid_regex, "$options": "i"}}
            ]
            for ip in all_ip_numbers:
                if ip:
                    barcode_query.append({"ipnumber": ip})

            # Check investigation bill numbers
            invest_bills = list(invest_coll.find({
                "$or": [
                    {"uhid": {"$regex": combined_uhid_regex, "$options": "i"}},
                    {"ipNumber": {"$in": list(all_ip_numbers)}}
                ]
            }, {"investBillNo": 1, "billNumber": 1}))
            bill_numbers = [b.get("investBillNo") or b.get("billNumber") for b in invest_bills if b.get("investBillNo") or b.get("billNumber")]
            if bill_numbers:
                barcode_query.append({"billnumber": {"$in": bill_numbers}})

            barcode_records = list(core_hmsbarcode.find({"$or": barcode_query}))
            found_barcodes = list(set([b.get("barcode") for b in barcode_records if b.get("barcode")]))

            # Helper to get parameter definition from core_testdetails
            def get_parameter_from_core(core_test, device_id, test_code=None, param_index=None):
                core_parameters = core_test.get("parameters", {})
                params_list = []
                if isinstance(core_parameters, dict):
                    if device_id and device_id != "N/A" and device_id in core_parameters:
                        params_list = core_parameters[device_id]
                    elif core_parameters:
                        params_list = list(core_parameters.values())[0]
                elif isinstance(core_parameters, list):
                    params_list = core_parameters

                if not isinstance(params_list, list):
                    return None
                if param_index is not None and 0 <= param_index < len(params_list):
                    return params_list[param_index]
                if test_code:
                    for p in params_list:
                        if isinstance(p, dict) and p.get("test_code") == test_code:
                            return p
                return None

            # Fetch standard test values from core_testvalue
            for bc in found_barcodes:
                tv_records = list(core_testvalue.find({"barcode": bc}))
                for tv in tv_records:
                    raw = tv.get("testdetails", "[]")
                    details = json.loads(raw) if isinstance(raw, str) else (raw or [])
                    if not isinstance(details, list):
                        continue

                    for test in details:
                        test_id = test.get("test_id")
                        device_id = test.get("device_id", "N/A")
                        parameters = test.get("parameters", [])
                        approve_by = test.get("approve_by", "")
                        approve_time = test.get("approve_time", "N/A")
                        verified_by = test.get("verified_by", "N/A")
                        comment = test.get("comment", "")
                        remarks = test.get("remarks", "")
                        is_approved = bool(test.get("approve") is True)

                        core_test = core_testdetails.find_one({"test_id": test_id}) if test_id else None
                        testname = core_test.get("test_name") if core_test else test.get("testname", "Diagnostic Test")
                        department = core_test.get("department") if core_test else test.get("department", "Diagnostics")
                        specimen_type = core_test.get("specimen_type") if core_test else test.get("specimen_type", "")

                        parsed_params = []
                        if parameters and len(parameters) > 0 and core_test:
                            for param_index, param_value in enumerate(parameters):
                                t_code = param_value.get("test_code")
                                val = param_value.get("value", "")
                                p_def = get_parameter_from_core(core_test, device_id, test_code=t_code, param_index=param_index)
                                if p_def:
                                    parsed_params.append({
                                        "name": p_def.get("test_name", param_value.get("name", "")),
                                        "test_code": t_code,
                                        "value": val,
                                        "unit": p_def.get("unit", ""),
                                        "reference_range": p_def.get("reference_range", ""),
                                        "method": p_def.get("method", ""),
                                        "comment": param_value.get("comment", "")
                                    })
                                else:
                                    parsed_params.append({
                                        "name": param_value.get("name", t_code or "Parameter"),
                                        "test_code": t_code,
                                        "value": val,
                                        "unit": param_value.get("unit", ""),
                                        "reference_range": param_value.get("reference_range", ""),
                                        "method": param_value.get("method", ""),
                                        "comment": param_value.get("comment", "")
                                    })
                        elif parameters and len(parameters) > 0:
                            for param_value in parameters:
                                parsed_params.append({
                                    "name": param_value.get("name", "Parameter"),
                                    "test_code": param_value.get("test_code", ""),
                                    "value": param_value.get("value", ""),
                                    "unit": param_value.get("unit", ""),
                                    "reference_range": param_value.get("reference_range", ""),
                                    "method": param_value.get("method", ""),
                                    "comment": param_value.get("comment", "")
                                })
                        else:
                            parsed_params.append({
                                "name": testname,
                                "test_code": test_id,
                                "value": test.get("value", ""),
                                "unit": core_test.get("unit", "") if core_test else test.get("unit", ""),
                                "reference_range": core_test.get("reference_range", "") if core_test else test.get("reference_range", ""),
                                "method": core_test.get("method", "") if core_test else test.get("method", ""),
                                "comment": comment
                            })

                        test_date = approve_time if (approve_time and approve_time != "N/A") else serialize_value(tv.get("created_date") or tv.get("test_date"))
                        lab_results.append({
                            "barcode": bc,
                            "test_id": test_id,
                            "test_name": testname,
                            "department": department,
                            "specimen_type": specimen_type,
                            "is_approved": is_approved,
                            "approve_by": approve_by,
                            "approve_time": approve_time,
                            "verified_by": verified_by,
                            "remarks": remarks,
                            "comment": comment,
                            "is_microbiology": False,
                            "parameters": parsed_params,
                            "date": test_date
                        })

                # Fetch microbiology test values from core_mbtestvalue
                mb_records = list(core_mbtestvalue.find({"barcode": bc}))
                for mb in mb_records:
                    raw_mb = mb.get("testdetails", "[]")
                    mb_details = json.loads(raw_mb) if isinstance(raw_mb, str) else (raw_mb or [])
                    if not isinstance(mb_details, list):
                        continue

                    for mb_test in mb_details:
                        mb_test_id = mb_test.get("test_id")
                        mb_test_name = mb_test.get("testname", "Microbiology Culture / Test")
                        mb_date = mb_test.get("approve_time") if (mb_test.get("approve_time") and mb_test.get("approve_time") != "N/A") else serialize_value(mb.get("created_date"))
                        lab_results.append({
                            "barcode": bc,
                            "test_id": mb_test_id,
                            "test_name": mb_test_name,
                            "department": "Microbiology",
                            "specimen_type": mb_test.get("specimen_type", ""),
                            "organism": mb_test.get("organism", ""),
                            "colony_count": mb_test.get("colony_count", ""),
                            "is_approved": bool(mb_test.get("approve") is True),
                            "approve_by": mb_test.get("approve_by", ""),
                            "approve_time": mb_test.get("approve_time", "N/A"),
                            "verified_by": mb_test.get("verified_by", "N/A"),
                            "remarks": mb_test.get("remarks", ""),
                            "is_microbiology": True,
                            "sensitivity": mb_test.get("sensitivity", []),
                            "parameters": [],
                            "date": mb_date
                        })

            # Sort lab results descending by date
            lab_results.sort(key=lambda x: str(x.get("date") or ""), reverse=True)

        # ── 5. Doctor Clinical Notes History ──
        doc_notes_cursor = list(doctor_notes_coll.find({
            "$or": [
                {"uhid": {"$regex": combined_uhid_regex, "$options": "i"}},
                {"ip_number": {"$in": list(all_ip_numbers)}}
            ]
        }))
        doc_notes = []
        for dn in doc_notes_cursor:
            doc_id = dn.get("doctor_id") or ""
            _, doc_name = resolve_doctor_id_and_name(doc_id)
            doc_notes.append({
                "id": str(dn.get("_id")),
                "ip_number": dn.get("ip_number", ""),
                "note_type": dn.get("note_type", "Clinical Progress Note"),
                "note_date": serialize_value(dn.get("note_date")),
                "doctor_name": doc_name or "Attending Physician",
                "is_finalized": bool(dn.get("is_finalized", False)),
                "chief_complaints": to_plain_json(dn.get("chief_complaints", [])),
                "provisional_diagnosis": to_plain_json(dn.get("provisional_diagnosis", {})),
                "plan_of_care": to_plain_json(dn.get("plan_of_care", {})),
                "physical_examination": to_plain_json(dn.get("physical_examination", {})),
                "past_history": to_plain_json(dn.get("past_history", {})),
                "allergies": to_plain_json(dn.get("allergies", []))
            })
        doc_notes.sort(key=lambda x: str(x.get("note_date") or ""), reverse=True)

        # ── 6. Nursing Bedside & Vitals History ──
        nursing_notes_cursor = list(nursing_notes_coll.find({
            "$or": [
                {"uhid": {"$regex": combined_uhid_regex, "$options": "i"}},
                {"ip_number": {"$in": list(all_ip_numbers)}}
            ]
        }))
        nursing_notes = []
        for nn in nursing_notes_cursor:
            nursing_notes.append({
                "id": str(nn.get("_id")),
                "ip_number": nn.get("ip_number", ""),
                "shift": nn.get("shift", "Morning"),
                "note_date": serialize_value(nn.get("note_date")),
                "is_finalized": bool(nn.get("is_finalized", False)),
                "vitals": to_plain_json(nn.get("vitals", {})),
                "pain_score": nn.get("pain_score", 0),
                "pain_severity": nn.get("pain_severity", "No Pain"),
                "pain_location": nn.get("pain_location", ""),
                "intake_output": to_plain_json(nn.get("intake_output", {})),
                "handover_notes": nn.get("handover_notes", "")
            })
        nursing_notes.sort(key=lambda x: str(x.get("note_date") or ""), reverse=True)

        # ── 7. Discharge Summaries ──
        summary_cursor = list(summary_coll.find({
            "$or": [
                {"uhid": {"$regex": combined_uhid_regex, "$options": "i"}},
                {"ipNo": {"$in": list(all_ip_numbers)}}
            ]
        }))
        discharge_summaries = []
        for sm in summary_cursor:
            discharge_summaries.append({
                "id": str(sm.get("_id")),
                "ip_number": sm.get("ipNo", ""),
                "summary_type": sm.get("summaryType", "Discharge Summary"),
                "heading": sm.get("heading", "Hospital Discharge Summary"),
                "created_date": serialize_value(sm.get("created_date")),
                "primary_diagnosis": sm.get("primaryDiagnosis") or sm.get("diagnosis") or "",
                "condition_at_discharge": sm.get("conditionAtDischarge") or "",
                "discharge_advice": sm.get("dischargeAdvice") or "",
                "hospital_course": sm.get("hospitalCourse") or sm.get("courseInHospital") or "",
                "fields_data": to_plain_json(sm.get("fieldsData", []))
            })
        discharge_summaries.sort(key=lambda x: str(x.get("created_date") or ""), reverse=True)

        # ── 8. Prescribed Medications History (Without Prices/Costs) ──
        medications = []
        pharm_bills = list(pharmacy_coll.find({
            "$or": [
                {"uhid": {"$regex": combined_uhid_regex, "$options": "i"}},
                {"ip_number": {"$in": list(all_ip_numbers)}},
                {"ipNumber": {"$in": list(all_ip_numbers)}}
            ]
        }).limit(50))
        pharm_item_cache = {}
        for itm in pharm_item_coll.find({}, {"item_id": 1, "item_name": 1, "brand_name": 1}):
            i_id = itm.get("item_id")
            if i_id is not None:
                pharm_item_cache[str(i_id)] = itm.get("item_name") or itm.get("brand_name") or f"Item #{i_id}"

        for pb in pharm_bills:
            b_date = serialize_value(pb.get("billing_date") or pb.get("created_date"))
            items = pb.get("items") or pb.get("bill_items") or []
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except Exception:
                    items = []

            for it in items:
                itm_id = str(it.get("item_id") or it.get("item") or "")
                itm_name = it.get("item_name") or pharm_item_cache.get(itm_id) or "Medication"
                medications.append({
                    "date": b_date,
                    "medicine_name": itm_name,
                    "dosage": it.get("dosage") or it.get("strength") or "",
                    "frequency": it.get("frequency") or "",
                    "duration": it.get("duration") or "",
                    "route": it.get("route") or "Oral",
                    "quantity": it.get("quantity") or it.get("qty") or "1"
                })

        # Also aggregate present medications from doctor notes
        for dn in doc_notes:
            pres_meds = dn.get("plan_of_care", {}).get("medications") or []
            if isinstance(pres_meds, list):
                for pm in pres_meds:
                    if pm.get("name") or pm.get("medicine"):
                        medications.append({
                            "date": dn.get("note_date"),
                            "medicine_name": pm.get("name") or pm.get("medicine"),
                            "dosage": pm.get("dose") or pm.get("dosage") or "",
                            "frequency": pm.get("frequency") or "",
                            "duration": pm.get("duration") or "",
                            "route": pm.get("route") or "Oral",
                            "quantity": "-"
                        })

        medications.sort(key=lambda x: str(x.get("date") or ""), reverse=True)

        return Response({
            "status": "success",
            "data": {
                "patient": patient_profile,
                "admissions": admissions,
                "op_visits": op_visits,
                "lab_investigations": lab_results,
                "doctor_notes": doc_notes,
                "nursing_notes": nursing_notes,
                "discharge_summaries": discharge_summaries,
                "medications": medications
            }
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print(f"Error in IPEMR_patient_history: {e}")
        return Response({
            "status": "error",
            "message": f"Server error generating patient history: {str(e)}"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def IPEMR_doctor_dashboard_analytics(request):
    """
    Comprehensive Analytics & Reporting for Inpatient Doctor Desk:
    - Overall Turnaround Time (TAT) from Admission to First Clinical Note
    - First Patient and Last Patient consultation times & rounding duration
    - Peak Rounding Hours distribution (00:00 - 23:00)
    - Patient Load Analysis by Doctor, Department, and Ward
    - Today's Admissions count and comparative trend
    - Already Seen Patients Today vs. Pending Rounds live tracker
    - Detailed drill-down patient report data
    """
    try:
        now_local = timezone.localtime(timezone.now()) if timezone.is_aware(timezone.now()) else timezone.now()
        today_str = now_local.strftime("%Y-%m-%d")

        date_from_str = request.GET.get("date_from", "").strip() or request.GET.get("date", "").strip() or today_str
        date_to_str = request.GET.get("date_to", "").strip() or date_from_str
        filter_doctor = request.GET.get("doctor_id", "").strip() or request.GET.get("doctor", "").strip()
        filter_dept = request.GET.get("department", "").strip()

        try:
            start_date = datetime.strptime(date_from_str, "%Y-%m-%d")
            start_dt = timezone.make_aware(datetime.combine(start_date.date(), datetime.min.time())) if timezone.is_aware(timezone.now()) else datetime.combine(start_date.date(), datetime.min.time())
        except Exception:
            start_dt = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

        try:
            end_date = datetime.strptime(date_to_str, "%Y-%m-%d")
            end_dt = timezone.make_aware(datetime.combine(end_date.date(), datetime.max.time())) if timezone.is_aware(timezone.now()) else datetime.combine(end_date.date(), datetime.max.time())
        except Exception:
            end_dt = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)

        # ── 1. Fetch Admitted Patients ──
        active_admissions = []
        if mongo_db is not None:
            adm_query = {
                "is_admitted": True,
                "is_cancelled": {"$ne": True},
                "is_discharged": {"$ne": True}
            }
            raw_adms = list(mongo_db["hospital_admission"].find(adm_query).sort("admissionDateTime", -1))
        else:
            raw_adms = []

        # Also get admissions created within the date range (including discharged if filtering historical)
        range_adm_query = {
            "is_cancelled": {"$ne": True},
            "admissionDateTime": {"$gte": start_dt, "$lte": end_dt}
        }
        range_admissions_raw = list(mongo_db["hospital_admission"].find(range_adm_query)) if mongo_db is not None else []

        # Today admissions query
        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        today_adm_count = mongo_db["hospital_admission"].count_documents({
            "is_cancelled": {"$ne": True},
            "admissionDateTime": {"$gte": today_start, "$lte": today_end}
        }) if mongo_db is not None else 0

        # Yesterday admissions query for comparison
        yesterday_start = today_start - timedelta(days=1)
        yesterday_end = today_end - timedelta(days=1)
        yesterday_adm_count = mongo_db["hospital_admission"].count_documents({
            "is_cancelled": {"$ne": True},
            "admissionDateTime": {"$gte": yesterday_start, "$lte": yesterday_end}
        }) if mongo_db is not None else 0

        # ── 2. Fetch Doctor Notes in Date Range ──
        notes_qs = IPDoctorNotes.objects.filter(note_date__gte=start_dt, note_date__lte=end_dt).order_by('note_date')
        if filter_doctor:
            clean_filt_doc, _ = resolve_doctor_id_and_name(filter_doctor)
            notes_qs = notes_qs.filter(doctor_id=clean_filt_doc or filter_doctor)

        notes_list = list(notes_qs)
        total_notes_count = len(notes_list)

        # ── 3. First Patient & Last Patient Round Timings ──
        first_patient_seen = None
        last_patient_seen = None
        rounding_span_minutes = 0

        if notes_list:
            # First note of the day/range
            fn = notes_list[0]
            _, fn_doc_name = resolve_doctor_id_and_name(fn.doctor_id)
            fn_pname = ""
            fn_room, fn_bed = "", ""
            if mongo_db is not None and fn.ip_number:
                adm_fn = mongo_db["hospital_admission"].find_one({"ipNumber": fn.ip_number}) or mongo_db["hospital_admission"].find_one({"ip_number": fn.ip_number})
                if adm_fn:
                    fn_room, fn_bed, _ = extract_admission_room_bed(adm_fn)
                    sal = adm_fn.get("salutation", "") or ""
                    f_name = adm_fn.get("firstName", "") or ""
                    l_name = adm_fn.get("lastName", "") or ""
                    fn_pname = f"{sal} {f_name} {l_name}".strip() or adm_fn.get("patientName", "")

            first_patient_seen = {
                "id": str(getattr(fn, '_id', None) or getattr(fn, 'id', '')),
                "ip_number": fn.ip_number,
                "uhid": fn.uhid,
                "patient_name": fn_pname or f"Patient ({fn.uhid or fn.ip_number})",
                "room_no": fn_room,
                "bed_no": fn_bed,
                "note_time": fn.note_date.isoformat() if fn.note_date else "",
                "note_time_formatted": ((timezone.localtime(fn.note_date) if timezone.is_aware(fn.note_date) else fn.note_date).strftime("%I:%M %p")) if fn.note_date else "",
                "doctor_id": fn.doctor_id,
                "doctor_name": fn_doc_name or fn.doctor_id,
                "note_type": fn.note_type,
                "is_finalized": fn.is_finalized
            }

            # Last note of the day/range
            ln = notes_list[-1]
            _, ln_doc_name = resolve_doctor_id_and_name(ln.doctor_id)
            ln_pname = ""
            ln_room, ln_bed = "", ""
            if mongo_db is not None and ln.ip_number:
                adm_ln = mongo_db["hospital_admission"].find_one({"ipNumber": ln.ip_number}) or mongo_db["hospital_admission"].find_one({"ip_number": ln.ip_number})
                if adm_ln:
                    ln_room, ln_bed, _ = extract_admission_room_bed(adm_ln)
                    sal = adm_ln.get("salutation", "") or ""
                    f_name = adm_ln.get("firstName", "") or ""
                    l_name = adm_ln.get("lastName", "") or ""
                    ln_pname = f"{sal} {f_name} {l_name}".strip() or adm_ln.get("patientName", "")

            last_patient_seen = {
                "id": str(getattr(ln, '_id', None) or getattr(ln, 'id', '')),
                "ip_number": ln.ip_number,
                "uhid": ln.uhid,
                "patient_name": ln_pname or f"Patient ({ln.uhid or ln.ip_number})",
                "room_no": ln_room,
                "bed_no": ln_bed,
                "note_time": ln.note_date.isoformat() if ln.note_date else "",
                "note_time_formatted": ((timezone.localtime(ln.note_date) if timezone.is_aware(ln.note_date) else ln.note_date).strftime("%I:%M %p")) if ln.note_date else "",
                "doctor_id": ln.doctor_id,
                "doctor_name": ln_doc_name or ln.doctor_id,
                "note_type": ln.note_type,
                "is_finalized": ln.is_finalized
            }

            if fn.note_date and ln.note_date:
                diff_sec = (ln.note_date - fn.note_date).total_seconds()
                rounding_span_minutes = max(0, int(diff_sec // 60))

        rounding_span_hours = round(rounding_span_minutes / 60, 1)
        rounding_span_formatted = f"{rounding_span_minutes // 60}h {rounding_span_minutes % 60}m" if rounding_span_minutes >= 60 else f"{rounding_span_minutes} mins"

        # ── 4. Peak Hours Distribution (00:00 to 23:00) ──
        hourly_counts = [0] * 24
        for note in notes_list:
            if note.note_date:
                note_local = timezone.localtime(note.note_date) if timezone.is_aware(note.note_date) else note.note_date
                h = note_local.hour
                if 0 <= h <= 23:
                    hourly_counts[h] += 1

        hours_data = []
        max_hour_count = 0
        peak_hour_idx = 10  # default 10 AM
        for h in range(24):
            count = hourly_counts[h]
            if count > max_hour_count:
                max_hour_count = count
                peak_hour_idx = h
            hr_label = datetime(2000, 1, 1, h, 0).strftime("%I %p").lstrip('0')
            hr_range = f"{datetime(2000, 1, 1, h, 0).strftime('%I:%M %p')} - {datetime(2000, 1, 1, (h+1)%24, 0).strftime('%I:%M %p')}"
            hours_data.append({
                "hour": h,
                "time_str": f"{h:02d}:00",
                "label": hr_label,
                "range": hr_range,
                "count": count
            })

        peak_hour_str = f"{datetime(2000, 1, 1, peak_hour_idx, 0).strftime('%I:%M %p')} - {datetime(2000, 1, 1, (peak_hour_idx+1)%24, 0).strftime('%I:%M %p')}" if max_hour_count > 0 else "N/A"

        # ── 5. Admitted Patients Processing: Seen vs Pending & TAT ──
        # Group notes by IP number for quick lookup
        ip_notes_in_range = {}
        for note in notes_list:
            ip_k = note.ip_number or ""
            if ip_k:
                if ip_k not in ip_notes_in_range:
                    ip_notes_in_range[ip_k] = []
                ip_notes_in_range[ip_k].append(note)

        # Build list of active admitted patients + range admissions
        seen_patients = []
        pending_patients = []
        all_patient_report = []

        tat_minutes_list = []
        doctor_load_map = {}
        dept_load_map = {}
        ward_load_map = {}

        processed_ips = set()

        for adm in raw_adms:
            ip_num = str(adm.get("ipNumber", "") or adm.get("ip_number", "") or "")
            uhid = str(adm.get("uhid", "") or "")
            if not ip_num or ip_num in processed_ips:
                continue
            processed_ips.add(ip_num)

            # Resolve Patient Profile
            patient_name = ""
            age = adm.get("age")
            gender = adm.get("gender") or adm.get("Gender") or ""
            blood_group = adm.get("blood_group") or adm.get("bloodGroup") or ""

            if uhid and mongo_db is not None:
                p_doc = mongo_db["hospital_patient"].find_one({"uhid": uhid})
                if p_doc:
                    sal = p_doc.get("salutation", "") or ""
                    fn = p_doc.get("firstName", "") or ""
                    ln = p_doc.get("lastName", "") or ""
                    patient_name = f"{sal} {fn} {ln}".strip()
                    if not age: age = p_doc.get("age")
                    gender = p_doc.get("gender") or gender
                    blood_group = p_doc.get("blood_group") or p_doc.get("bloodGroup") or blood_group

            if not patient_name:
                sal = adm.get("salutation", "") or ""
                fn = adm.get("firstName", "") or ""
                ln = adm.get("lastName", "") or ""
                patient_name = f"{sal} {fn} {ln}".strip() or adm.get("patientName", "") or f"Patient ({uhid or ip_num})"

            # Room & Bed
            room_no, bed_no, block_name = extract_admission_room_bed(adm)

            # Doctor & Department
            admitting_doc_raw = adm.get("admittingDoctor", "") or adm.get("consultingDoctor", "") or ""
            clean_doc_id, resolved_doc_name = resolve_doctor_id_and_name(admitting_doc_raw)
            dept = adm.get("department", "") or adm.get("departmentName", "") or "General Medicine"

            # Apply Doctor / Dept Filter
            if filter_doctor:
                clean_filt_doc, _ = resolve_doctor_id_and_name(filter_doctor)
                if (clean_filt_doc and clean_filt_doc.lower() not in clean_doc_id.lower() and clean_filt_doc.lower() not in resolved_doc_name.lower()) and \
                   (filter_doctor.lower() not in clean_doc_id.lower() and filter_doctor.lower() not in resolved_doc_name.lower()):
                    continue

            if filter_dept and filter_dept.lower() not in dept.lower():
                continue

            adm_dt = adm.get("admissionDateTime")
            if isinstance(adm_dt, str):
                try:
                    adm_dt = datetime.fromisoformat(adm_dt.replace("Z", "+00:00"))
                except Exception:
                    adm_dt = None

            # Calculate TAT from Admission to First Doctor Note EVER for this admission
            first_ever_note = IPDoctorNotes.objects.filter(ip_number=ip_num).order_by('note_date').first()
            tat_mins = None
            tat_formatted = "-"
            if adm_dt and first_ever_note and first_ever_note.note_date:
                try:
                    note_dt = first_ever_note.note_date
                    if timezone.is_aware(adm_dt) and not timezone.is_aware(note_dt):
                        note_dt = timezone.make_aware(note_dt)
                    elif not timezone.is_aware(adm_dt) and timezone.is_aware(note_dt):
                        adm_dt = timezone.make_aware(adm_dt)
                    sec_diff = (note_dt - adm_dt).total_seconds()
                    if sec_diff >= 0:
                        tat_mins = int(sec_diff // 60)
                        tat_minutes_list.append(tat_mins)
                        if tat_mins < 60:
                            tat_formatted = f"{tat_mins} mins"
                        else:
                            tat_formatted = f"{tat_mins // 60}h {tat_mins % 60}m"
                except Exception:
                    pass

            # Check if seen in the selected Date Range
            patient_notes_in_range = ip_notes_in_range.get(ip_num, [])
            is_seen = len(patient_notes_in_range) > 0
            latest_note_in_range = patient_notes_in_range[-1] if is_seen else None
            first_note_in_range = patient_notes_in_range[0] if is_seen else None

            # Waiting time if pending
            waiting_time_hours = 0
            if not is_seen and adm_dt:
                try:
                    cur_now = timezone.now() if timezone.is_aware(adm_dt) else datetime.now()
                    diff_w = (cur_now - adm_dt).total_seconds()
                    waiting_time_hours = round(diff_w / 3600, 1)
                except Exception:
                    pass

            patient_card = {
                "id": str(adm.get("_id", "")),
                "ip_number": ip_num,
                "uhid": uhid,
                "patient_name": patient_name,
                "age": age,
                "gender": gender,
                "blood_group": blood_group,
                "room_no": room_no,
                "bed_no": bed_no,
                "ward_name": block_name or "General Ward",
                "doctor_id": clean_doc_id,
                "doctor_name": resolved_doc_name or clean_doc_id or "Attending Physician",
                "department": dept,
                "admission_date": adm_dt.isoformat() if isinstance(adm_dt, datetime) else str(adm_dt or ""),
                "admission_date_formatted": ((timezone.localtime(adm_dt) if timezone.is_aware(adm_dt) else adm_dt).strftime("%d/%m/%Y %I:%M %p")) if isinstance(adm_dt, datetime) else str(adm_dt or ""),
                "is_seen": is_seen,
                "status": "Seen" if is_seen else "Pending Round",
                "notes_count_today": len(patient_notes_in_range),
                "first_note_time": first_note_in_range.note_date.isoformat() if first_note_in_range and first_note_in_range.note_date else "",
                "first_note_time_formatted": ((timezone.localtime(first_note_in_range.note_date) if timezone.is_aware(first_note_in_range.note_date) else first_note_in_range.note_date).strftime("%I:%M %p")) if first_note_in_range and first_note_in_range.note_date else "-",
                "latest_note_time": latest_note_in_range.note_date.isoformat() if latest_note_in_range and latest_note_in_range.note_date else "",
                "latest_note_time_formatted": ((timezone.localtime(latest_note_in_range.note_date) if timezone.is_aware(latest_note_in_range.note_date) else latest_note_in_range.note_date).strftime("%I:%M %p")) if latest_note_in_range and latest_note_in_range.note_date else "-",
                "latest_note_type": latest_note_in_range.note_type if latest_note_in_range else "-",
                "tat_minutes": tat_mins,
                "tat_formatted": tat_formatted,
                "waiting_time_hours": waiting_time_hours
            }

            all_patient_report.append(patient_card)

            if is_seen:
                seen_patients.append(patient_card)
            else:
                pending_patients.append(patient_card)

            # Aggregations for Doctor Load
            doc_key = resolved_doc_name or clean_doc_id or "Unassigned"
            if doc_key not in doctor_load_map:
                doctor_load_map[doc_key] = {
                    "doctor_name": doc_key,
                    "doctor_id": clean_doc_id,
                    "total_patients": 0,
                    "seen_patients": 0,
                    "pending_patients": 0,
                    "notes_written": 0,
                    "tat_list": []
                }
            doctor_load_map[doc_key]["total_patients"] += 1
            if is_seen:
                doctor_load_map[doc_key]["seen_patients"] += 1
                doctor_load_map[doc_key]["notes_written"] += len(patient_notes_in_range)
            else:
                doctor_load_map[doc_key]["pending_patients"] += 1
            if tat_mins is not None:
                doctor_load_map[doc_key]["tat_list"].append(tat_mins)

            # Department Load
            dept_key = dept or "General Medicine"
            if dept_key not in dept_load_map:
                dept_load_map[dept_key] = {"department": dept_key, "total": 0, "seen": 0, "pending": 0}
            dept_load_map[dept_key]["total"] += 1
            if is_seen:
                dept_load_map[dept_key]["seen"] += 1
            else:
                dept_load_map[dept_key]["pending"] += 1

            # Ward Load
            ward_key = block_name or "General Ward"
            if ward_key not in ward_load_map:
                ward_load_map[ward_key] = {"ward_name": ward_key, "total": 0, "seen": 0, "pending": 0}
            ward_load_map[ward_key]["total"] += 1
            if is_seen:
                ward_load_map[ward_key]["seen"] += 1
            else:
                ward_load_map[ward_key]["pending"] += 1

        # ── 6. TAT Statistical Calculation ──
        avg_tat_minutes = 0
        median_tat_minutes = 0
        min_tat_minutes = 0
        max_tat_minutes = 0
        tat_buckets = {
            "under_1hr": 0,
            "1_to_3hrs": 0,
            "3_to_6hrs": 0,
            "over_6hrs": 0
        }

        if tat_minutes_list:
            avg_tat_minutes = round(sum(tat_minutes_list) / len(tat_minutes_list), 1)
            sorted_tats = sorted(tat_minutes_list)
            mid = len(sorted_tats) // 2
            median_tat_minutes = sorted_tats[mid] if len(sorted_tats) % 2 != 0 else round((sorted_tats[mid - 1] + sorted_tats[mid]) / 2, 1)
            min_tat_minutes = sorted_tats[0]
            max_tat_minutes = sorted_tats[-1]

            for t in tat_minutes_list:
                if t < 60:
                    tat_buckets["under_1hr"] += 1
                elif 60 <= t < 180:
                    tat_buckets["1_to_3hrs"] += 1
                elif 180 <= t < 360:
                    tat_buckets["3_to_6hrs"] += 1
                else:
                    tat_buckets["over_6hrs"] += 1

        avg_tat_formatted = f"{int(avg_tat_minutes // 60)}h {int(avg_tat_minutes % 60)}m" if avg_tat_minutes >= 60 else f"{int(avg_tat_minutes)} mins" if avg_tat_minutes > 0 else "-"

        # Format Doctor Load List
        doctor_load_list = []
        for d in doctor_load_map.values():
            d_tats = d.pop("tat_list", [])
            d_avg_tat = round(sum(d_tats) / len(d_tats), 1) if d_tats else 0
            d["avg_tat_minutes"] = d_avg_tat
            d["avg_tat_formatted"] = f"{int(d_avg_tat // 60)}h {int(d_avg_tat % 60)}m" if d_avg_tat >= 60 else f"{int(d_avg_tat)} mins" if d_avg_tat > 0 else "-"
            d["completion_rate"] = round((d["seen_patients"] / d["total_patients"] * 100), 1) if d["total_patients"] > 0 else 0
            doctor_load_list.append(d)

        doctor_load_list.sort(key=lambda x: x["total_patients"], reverse=True)
        department_load_list = sorted(dept_load_map.values(), key=lambda x: x["total"], reverse=True)
        ward_load_list = sorted(ward_load_map.values(), key=lambda x: x["total"], reverse=True)

        # ── 7. KPI Summary Object ──
        total_admitted_count = len(all_patient_report)
        seen_count = len(seen_patients)
        pending_count = len(pending_patients)
        rounding_completion_pct = round((seen_count / total_admitted_count * 100), 1) if total_admitted_count > 0 else 0

        kpis = {
            "overall_avg_tat_minutes": avg_tat_minutes,
            "overall_avg_tat_formatted": avg_tat_formatted,
            "median_tat_minutes": median_tat_minutes,
            "min_tat_minutes": min_tat_minutes,
            "max_tat_minutes": max_tat_minutes,
            "tat_buckets": tat_buckets,
            "admissions_today": today_adm_count,
            "admissions_yesterday": yesterday_adm_count,
            "admissions_trend": today_adm_count - yesterday_adm_count,
            "total_active_admitted": total_admitted_count,
            "seen_patients_count": seen_count,
            "pending_patients_count": pending_count,
            "rounding_completion_pct": rounding_completion_pct,
            "total_notes_written": total_notes_count,
            "rounding_span_minutes": rounding_span_minutes,
            "rounding_span_formatted": rounding_span_formatted,
            "peak_hour": peak_hour_str,
            "peak_hour_count": max_hour_count
        }

        return Response({
            "status": "success",
            "date_range": {
                "date_from": date_from_str,
                "date_to": date_to_str
            },
            "kpis": kpis,
            "first_patient_seen": first_patient_seen,
            "last_patient_seen": last_patient_seen,
            "peak_hours_distribution": hours_data,
            "doctor_load_analysis": doctor_load_list,
            "department_load_analysis": department_load_list,
            "ward_load_analysis": ward_load_list,
            "seen_patients": seen_patients,
            "pending_patients": pending_patients,
            "all_patient_report": all_patient_report
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({
            "status": "error",
            "message": f"Server error generating doctor dashboard analytics: {str(e)}"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



