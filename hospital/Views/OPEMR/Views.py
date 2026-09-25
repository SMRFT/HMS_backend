import os
from pymongo import MongoClient
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from bson import Decimal128
from django.utils.timezone import now
from django.db.models import Q
from hospital.models import Patient, Billing
from .models import VitalEntry,  OPDoctorConsultation
from .serializer import VitalEntrySerializer,  OPDoctorConsultationSerializer


# Auth/permissions
import json
import re
import mimetypes
import gridfs
from bson.objectid import ObjectId
from django.http import HttpResponse
from pyauth.auth import HasRoleAndDataPermission, HasRolePermission
from rest_framework.permissions import AllowAny
from ..dbcollection import Diagnostics_test_details, HMS_Symptoms_list, medicine_package, profile_collection, doctor_role_code, Diagnostics_db, hms_db, hms_billtype, hospital_investigationprice







def safe_float(val):
    if val is None:
        return 0.0
    if isinstance(val, Decimal128):
        return float(val.to_decimal())
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def safe_isoformat(val):
    if not val:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_get_billing_patient(request):
    """
    Get patient details for paid billed patients only using Django ORM Billing and Patient models.
    """
    try:

        data = request.data
        employee_id = data.get("auth-user-id")
        # Query only paid bills via Django ORM Billing model (no doctor filter)
        paid_bills = Billing.objects.filter(payment_status__in=['Paid', 'paid', 'PAID']).select_related('patient').order_by('-billed_date')


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
                if vital_entry_obj and getattr(vital_entry_obj, 'created_date', None):
                    from django.utils import timezone
                    if vital_entry_obj.created_date.date() == timezone.now().date():
                        is_completed_today = True
                        latest_vital = VitalEntrySerializer(vital_entry_obj).data

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
            payment_status__in=['Paid', 'paid', 'PAID'],
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
                if vital_entry_obj and getattr(vital_entry_obj, 'created_date', None):
                    from django.utils import timezone
                    if vital_entry_obj.created_date.date() == timezone.now().date():
                        is_completed_today = True
                        latest_vital = VitalEntrySerializer(vital_entry_obj).data

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
        uhid_val = data.get("uhid")
        data['created_by'] = employee_id
        data['created_date'] = now()
        data['lastmodified_by'] = None
        data['lastmodified_date'] = None

        # Parse existing attachments list if provided
        attachments_data = data.get("attachments")
        if isinstance(attachments_data, str):
            try:
                attachments_data = json.loads(attachments_data)
            except Exception:
                attachments_data = []
        elif not isinstance(attachments_data, list):
            attachments_data = []

        # Handle any files uploaded directly in this request
        direct_files = request.FILES.getlist('files') or ([request.FILES['file']] if request.FILES.get('file') else [])
        if direct_files:
            try:
                fs = gridfs.GridFS(hms_db)
                for f_obj in direct_files:
                    safe_name = re.sub(r'[^a-zA-Z0-9_\.\-]', '_', getattr(f_obj, 'name', 'vital_doc'))
                    c_type = getattr(f_obj, 'content_type', None) or mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'
                    fid = fs.put(f_obj, filename=safe_name, content_type=c_type)
                    relative_url = f"/_b_a_c_k_e_n_d/HMS/OPEMR_get_vital_file/{str(fid)}/"
                    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip()
                    f_url = f"{public_base_url.rstrip('/')}{relative_url}" if public_base_url else request.build_absolute_uri(relative_url)
                    attachments_data.append({
                        "file_id": str(fid),
                        "file_name": safe_name,
                        "file_type": c_type,
                        "file_size": getattr(f_obj, 'size', 0),
                        "category": data.get("category") or "Old Hospital File",
                        "title": data.get("title") or "",
                        "url": f_url,
                        "uploaded_at": now().isoformat()
                    })
            except Exception as f_err:
                print("Error saving direct files to GridFS:", f_err)

        data['attachments'] = attachments_data

        # Check if record already exists for today or by provided id
        vital_id = data.get("id") or data.get("vital_entry_id")
        existing_vital = None
        if vital_id:
            existing_vital = VitalEntry.objects.filter(id=vital_id).first()
        elif uhid_val:
            today_start = now().replace(hour=0, minute=0, second=0, microsecond=0)
            existing_vital = VitalEntry.objects.filter(uhid=uhid_val, created_date__gte=today_start).order_by('-created_date').first()

        if existing_vital:
            serializer = VitalEntrySerializer(existing_vital, data=data, partial=True)
        else:
            serializer = VitalEntrySerializer(data=data)

        if serializer.is_valid():
            serializer.save()
            if uhid_val:
                try:
                    Billing.objects.filter(patient__uhid=uhid_val).update(consultation_status='Ready')
                except Exception as b_err:
                    print("Error updating Billing status:", b_err)
            return Response(
                {
                    "message": "Vital entry saved successfully.",
                    "data": serializer.data
                },
                status=status.HTTP_200_OK if existing_vital else status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_upload_vital_file(request):
    """
    Upload one or multiple vital room patient documents (old hospital files, reports, images, etc.)
    to MongoDB GridFS in 'HMS' database and return metadata with preview URL.
    Directly uses hms_db from dbcollection.py.
    """
    try:
        files = request.FILES.getlist('files')
        if not files and request.FILES.get('file'):
            files = [request.FILES['file']]

        if not files:
            return Response({"success": False, "error": "No file uploaded."}, status=status.HTTP_400_BAD_REQUEST)

        fs = gridfs.GridFS(hms_db)

        uploaded_records = []
        category = request.data.get('category') or request.POST.get('category') or 'Old Hospital File'
        title = request.data.get('title') or request.POST.get('title') or ''

        for file_obj in files:
            safe_name = re.sub(r'[^a-zA-Z0-9_\.\-]', '_', getattr(file_obj, 'name', 'vital_doc'))
            content_type = getattr(file_obj, 'content_type', None) or mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'
            file_id = fs.put(
                file_obj,
                filename=safe_name,
                content_type=content_type,
                metadata={
                    "category": category,
                    "title": title,
                    "uploaded_at": now().isoformat()
                }
            )

            relative_url = f"/_b_a_c_k_e_n_d/HMS/OPEMR_get_vital_file/{str(file_id)}/"
            public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip()
            if public_base_url:
                file_url = f"{public_base_url.rstrip('/')}{relative_url}"
            else:
                file_url = request.build_absolute_uri(relative_url)

            uploaded_records.append({
                "file_id": str(file_id),
                "file_name": safe_name,
                "file_type": content_type,
                "file_size": getattr(file_obj, 'size', 0),
                "category": category,
                "title": title,
                "url": file_url,
                "uploaded_at": now().isoformat()
            })

        return Response({
            "success": True,
            "message": f"{len(uploaded_records)} file(s) uploaded successfully.",
            "data": uploaded_records if len(uploaded_records) > 1 else uploaded_records[0],
            "files": uploaded_records
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def OPEMR_get_vital_file(request, file_id):
    """
    Serves vital room documents directly from MongoDB GridFS with inline preview support.
    Directly uses hms_db from dbcollection.py.
    """
    try:
        raw_id = str(file_id or "").strip()
        if not ObjectId.is_valid(raw_id):
            return HttpResponse("Invalid file ID", status=400)

        fs = gridfs.GridFS(hms_db)
        grid_file = fs.get(ObjectId(raw_id))
        if not grid_file:
            return HttpResponse("File not found", status=404)

        content_type = getattr(grid_file, 'content_type', None) or mimetypes.guess_type(grid_file.filename)[0] or 'application/octet-stream'
        response = HttpResponse(grid_file.read(), content_type=content_type)
        response["Content-Disposition"] = f'inline; filename="{grid_file.filename}"'
        return response
    except Exception as e:
        return HttpResponse(f"Error retrieving file: {str(e)}", status=500)


@api_view(['DELETE', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_delete_vital_file(request, file_id):
    """
    Deletes a document from MongoDB GridFS in 'HMS' database by file_id.
    """
    try:
        raw_id = str(file_id or "").strip()
        if not ObjectId.is_valid(raw_id):
            return Response({"success": False, "error": "Invalid file ID."}, status=status.HTTP_400_BAD_REQUEST)

        fs = gridfs.GridFS(hms_db)
        oid = ObjectId(raw_id)
        if fs.exists(oid):
            fs.delete(oid)
            return Response({"success": True, "message": "File deleted successfully from storage."}, status=status.HTTP_200_OK)
        else:
            return Response({"success": True, "message": "File already removed from storage."}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
def OPEMR_get_radiology_items(request):
    """
    Retrieve radiology items (X-Ray, MRI, CT, USG) for OPEMR consultation dropdowns.
    Matches billTypeNo from hms_billtype into hospital_investigationprice to get all investigation items,
    and groups them into relevant radiology categories (CT, MRI, X-Ray, USG).
    """
    try:
        # 1. Fetch active bill types from hms_billtype
        bill_type_docs = list(hms_billtype.find({"is_active": True})) if hms_billtype is not None else []
        if not bill_type_docs and hms_billtype is not None:
            bill_type_docs = list(hms_billtype.find({}))

        billtype_map = {}
        for bt in bill_type_docs:
            bno = str(bt.get("billTypeNo") or "").strip()
            if bno:
                if bno not in billtype_map:
                    billtype_map[bno] = []
                billtype_map[bno].append(bt)

        # 2. Match billTypeNo into hospital_investigationprice
        matched_inv_docs = []
        if hospital_investigationprice is not None:
            if billtype_map:
                matched_inv_docs = list(hospital_investigationprice.find({
                    "billTypeNo": {"$in": list(billtype_map.keys())},
                    "is_active": True
                }))
                if not matched_inv_docs:
                    matched_inv_docs = list(hospital_investigationprice.find({
                        "billTypeNo": {"$in": list(billtype_map.keys())}
                    }))

            # Ensure any other active investigation price documents are also considered
            all_active = list(hospital_investigationprice.find({"is_active": True}))
            seen_ids = set(str(d.get("_id")) for d in matched_inv_docs)
            for d in all_active:
                if str(d.get("_id")) not in seen_ids:
                    matched_inv_docs.append(d)

        # 3. Categorize items for CT, MRI, X-Ray, and USG dropdowns
        ct_items = []
        mri_items = []
        xray_items = []
        usg_items = []
        all_items = []

        seen_ct = set()
        seen_mri = set()
        seen_xray = set()
        seen_usg = set()

        for doc in matched_inv_docs:
            btn = str(doc.get("billTypeNo") or "").strip().upper()
            bt = str(doc.get("BillType") or "").strip()
            bt_upper = bt.upper()

            is_ct = btn.startswith("CT") or "CT" in bt_upper or "CT" in btn
            is_mri = btn.startswith("MRI") or "MRI" in bt_upper or "MRI" in btn
            is_xray = "XRAY" in btn or "X-RAY" in btn or "XRAY" in bt_upper or "X-RAY" in bt_upper
            is_usg = "USG" in btn or "USG" in bt_upper or "ULTRASOUND" in bt_upper or ("SCAN" in bt_upper and not is_ct and not is_mri)

            category = "Other"
            if is_ct:
                category = "CT"
            elif is_mri:
                category = "MRI"
            elif is_xray:
                category = "X-Ray"
            elif is_usg:
                category = "USG"

            items = doc.get("Items", [])
            for itm in items:
                if not isinstance(itm, dict):
                    continue
                name = str(itm.get("itemName") or "").strip()
                if not name:
                    continue

                item_id = itm.get("item_id")
                if item_id is None:
                    item_id = itm.get("id") or name

                price = 0.0
                if "price" in itm:
                    price = safe_float(itm["price"])
                else:
                    for k, v in itm.items():
                        if k not in ["itemName", "item_id", "id", "nabh_code"]:
                            if isinstance(v, (int, float, str)):
                                try:
                                    price = float(v)
                                    break
                                except (ValueError, TypeError):
                                    pass
                            elif isinstance(v, dict) and "price" in v:
                                try:
                                    price = float(v["price"])
                                    break
                                except (ValueError, TypeError):
                                    pass

                item_obj = {
                    "id": item_id,
                    "item_id": item_id,
                    "name": name,
                    "itemName": name,
                    "billTypeNo": doc.get("billTypeNo"),
                    "BillType": bt,
                    "category": category,
                    "price": price
                }

                all_items.append(item_obj)

                name_key = name.lower()
                if is_ct and name_key not in seen_ct:
                    seen_ct.add(name_key)
                    ct_items.append(item_obj)
                elif is_mri and name_key not in seen_mri:
                    seen_mri.add(name_key)
                    mri_items.append(item_obj)
                elif is_xray and name_key not in seen_xray:
                    seen_xray.add(name_key)
                    xray_items.append(item_obj)
                elif is_usg and name_key not in seen_usg:
                    seen_usg.add(name_key)
                    usg_items.append(item_obj)

        ct_items.sort(key=lambda x: x["name"])
        mri_items.sort(key=lambda x: x["name"])
        xray_items.sort(key=lambda x: x["name"])
        usg_items.sort(key=lambda x: x["name"])
        all_items.sort(key=lambda x: x["name"])

        return Response({
            "success": True,
            "ct": ct_items,
            "mri": mri_items,
            "xray": xray_items,
            "usg": usg_items,
            "data": {
                "ct": ct_items,
                "mri": mri_items,
                "xray": xray_items,
                "usg": usg_items
            },
            "all": all_items
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_get_medicines(request):
    """
    Get medicines list from medicine_package (hospital_pharmacyitem) dbcollection.py.
    Displays item_name in dropdown, returns item_id to store upon selection.
    Also retrieves batch_number, expiry_date, mrp, and available batches from pharmacy stock.
    """
    try:
        from hospital.Views.dbcollection import hms_db

        # Build batch map from pharmacy stock, velavan stock, and grn
        batch_map = {}

        # 1. hospital_pharmacystock (primary pharmacy stock)
        try:
            for s in hms_db['hospital_pharmacystock'].find():
                iid = s.get('item_id')
                bn = s.get('batch_number')
                if iid is not None and bn:
                    try:
                        iid_key = int(iid)
                    except Exception:
                        iid_key = iid
                    tot = float(s.get('total_stock', 0) or 0)
                    sold = float(s.get('sold_quantity', 0) or 0)
                    blk = float(s.get('blocked_quantity', 0) or 0)
                    avail = tot - sold - blk
                    exp = s.get('expiry_date')
                    exp_str = exp.strftime('%Y-%m-%d') if hasattr(exp, 'strftime') else str(exp or '')
                    mrp_val = float(str(s.get('mrp', 0) or 0))
                    price_val = float(str(s.get('Selling_Price', 0) or mrp_val))
                    entry = {
                        'batch_number': str(bn).strip(),
                        'expiry_date': exp_str,
                        'mrp': mrp_val,
                        'price': price_val,
                        'available_stock': avail
                    }
                    if iid_key not in batch_map:
                        batch_map[iid_key] = []
                    batch_map[iid_key].append(entry)
        except Exception as e:
            print("Error loading pharmacystock batches:", e)

        # 2. hospital_velavan_stock
        try:
            for v in hms_db['hospital_velavan_stock'].find():
                iid = v.get('item_id')
                bn = v.get('batch_no')
                if iid is not None and bn:
                    try:
                        iid_key = int(iid)
                    except Exception:
                        iid_key = iid
                    if iid_key not in batch_map:
                        batch_map[iid_key] = []
                    if not any(x['batch_number'] == str(bn).strip() for x in batch_map[iid_key]):
                        avail = float(v.get('total_quantity', 0) or 0) - float(v.get('sold_quantity', 0) or 0)
                        exp_str = str(v.get('expiry', '') or '')
                        mrp_val = float(str(v.get('mrp', 0) or 0))
                        batch_map[iid_key].append({
                            'batch_number': str(bn).strip(),
                            'expiry_date': exp_str,
                            'mrp': mrp_val,
                            'price': mrp_val,
                            'available_stock': avail
                        })
        except Exception as e:
            print("Error loading velavan batches:", e)

        # 3. hospital_grn
        try:
            for g in hms_db['hospital_grn'].find():
                items = g.get('items', [])
                if isinstance(items, list):
                    for it in items:
                        if isinstance(it, dict):
                            iid = it.get('item_id')
                            bn = it.get('batch')
                            if iid is not None and bn:
                                try:
                                    iid_key = int(iid)
                                except Exception:
                                    iid_key = iid
                                if iid_key not in batch_map:
                                    batch_map[iid_key] = []
                                if not any(x['batch_number'] == str(bn).strip() for x in batch_map[iid_key]):
                                    batch_map[iid_key].append({
                                        'batch_number': str(bn).strip(),
                                        'expiry_date': str(it.get('expiry', '') or ''),
                                        'mrp': float(it.get('mrp', 0) or 0),
                                        'price': float(it.get('selling_price', 0) or it.get('mrp', 0) or 0),
                                        'available_stock': float(it.get('quantity', 0) or 0)
                                    })
        except Exception as e:
            print("Error loading grn batches:", e)

        docs = list(medicine_package.find({"is_active": True}))
        if not docs:
            docs = list(medicine_package.find({}))

        medicines = []
        for doc in docs:
            m_id = doc.get("item_id")
            m_name = doc.get("item_name")
            if m_id is not None and m_name:
                try:
                    num_id = int(m_id) if str(m_id).isdigit() else m_id
                except Exception:
                    num_id = m_id

                # Get batch info
                batches = batch_map.get(num_id, [])
                if not batches and isinstance(num_id, int):
                    batches = batch_map.get(str(num_id), [])

                best_batch = ""
                exp_date = ""
                mrp = 0.0
                price = 0.0
                if batches:
                    with_stock = [b for b in batches if b.get('available_stock', 0) > 0]
                    chosen = with_stock[0] if with_stock else batches[0]
                    best_batch = chosen.get('batch_number', '')
                    exp_date = chosen.get('expiry_date', '')
                    mrp = chosen.get('mrp', 0.0)
                    price = chosen.get('price', 0.0)

                medicines.append({
                    "item_id": num_id,
                    "item_name": str(m_name).strip(),
                    "category": doc.get("category", "") or "",
                    "chemical_composition": doc.get("chemical_composition", "") or "",
                    "batch_number": best_batch,
                    "batch_no": best_batch,
                    "batches": [b.get('batch_number') for b in batches],
                    "expiry_date": exp_date,
                    "mrp": mrp,
                    "price": price
                })

        medicines.sort(key=lambda x: x["item_name"])
        return Response(medicines, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



def enrich_consultation_investigation_names(consult_dict):
    """
    Dynamically compares billTypeNo + item_id against hospital_investigationprice to get itemName,
    and test_id against Diagnostics_test_details to get test_name,
    attaching resolved names on GET so MongoDB never stores investigation names.
    """
    if not isinstance(consult_dict, dict):
        return consult_dict

    consult_copy = dict(consult_dict)
    from hospital.Views.dbcollection import hospital_investigationprice, Diagnostics_test_details

    # Cache radiology items map: (billTypeNo, item_id) -> (itemName, category)
    rad_name_map = {}
    try:
        if hospital_investigationprice is not None:
            inv_prices = list(hospital_investigationprice.find({"is_active": True})) or list(hospital_investigationprice.find({}))
            for doc in inv_prices:
                b_no = str(doc.get("billTypeNo") or "").strip().upper()
                b_type = str(doc.get("BillType") or "").strip().upper()
                cat = "CT" if ("CT" in b_no or "CT" in b_type) else (
                    "MRI" if ("MRI" in b_no or "MRI" in b_type) else (
                        "X-Ray" if ("XRAY" in b_no or "XRAY" in b_type) else (
                            "USG" if ("USG" in b_no or "USG" in b_type) else "Radiology"
                        )
                    )
                )
                for it in doc.get("Items", []):
                    if isinstance(it, dict) and it.get("item_id") is not None:
                        try:
                            iid = int(it.get("item_id"))
                        except Exception:
                            iid = it.get("item_id")
                        name = it.get("itemName") or ""
                        rad_name_map[(b_no, iid)] = (name, cat)
                        rad_name_map[(b_no, str(iid))] = (name, cat)
                        if iid not in rad_name_map:
                            rad_name_map[iid] = (name, cat)
                        if str(iid) not in rad_name_map:
                            rad_name_map[str(iid)] = (name, cat)
    except Exception as e:
        print("Error building rad_name_map in enrich_consultation_investigation_names:", e)

    # Cache lab tests map: test_id -> (test_name, department)
    lab_test_map = {}
    try:
        if Diagnostics_test_details is not None:
            lab_tests = list(Diagnostics_test_details.find({}))
            for lt in lab_tests:
                tid = lt.get("test_id")
                if tid is not None:
                    try:
                        tid_key = int(tid)
                    except Exception:
                        tid_key = tid
                    tname = lt.get("test_name") or ""
                    dept = lt.get("department") or "Diagnostics"
                    lab_test_map[tid_key] = (tname, dept)
                    lab_test_map[str(tid_key)] = (tname, dept)
    except Exception as e:
        print("Error building lab_test_map in enrich_consultation_investigation_names:", e)

    def enrich_rad_list(rad_list, default_cat):
        if not isinstance(rad_list, list):
            return rad_list
        enriched = []
        for it in rad_list:
            if not isinstance(it, dict):
                continue
            it_c = dict(it)
            bno = str(it_c.get("billTypeNo") or "").strip().upper()
            iid = it_c.get("item_id") if it_c.get("item_id") is not None else it_c.get("id")
            try:
                iid_key = int(iid)
            except Exception:
                iid_key = iid
            matched = rad_name_map.get((bno, iid_key)) or rad_name_map.get(iid_key)
            name = matched[0] if matched else (it_c.get("item_name") or it_c.get("name") or "")
            cat = matched[1] if matched else default_cat
            it_c["item_name"] = name
            it_c["name"] = name
            it_c["category"] = cat
            enriched.append(it_c)
        return enriched

    if "ct_scan_details" in consult_copy:
        consult_copy["ct_scan_details"] = enrich_rad_list(consult_copy.get("ct_scan_details"), "CT")
    if "mri_scan_details" in consult_copy:
        consult_copy["mri_scan_details"] = enrich_rad_list(consult_copy.get("mri_scan_details"), "MRI")
    if "xray_details" in consult_copy:
        consult_copy["xray_details"] = enrich_rad_list(consult_copy.get("xray_details"), "X-Ray")
    if "usg_details" in consult_copy:
        consult_copy["usg_details"] = enrich_rad_list(consult_copy.get("usg_details"), "USG")

    if "investigation_details" in consult_copy:
        raw_inv = consult_copy.get("investigation_details")
        if isinstance(raw_inv, list):
            enriched_inv = []
            for it in raw_inv:
                if not isinstance(it, dict):
                    continue
                it_c = dict(it)
                bno = str(it_c.get("billTypeNo") or "").strip().upper()
                iid = it_c.get("item_id")
                tid = it_c.get("test_id")
                if bno or (iid is not None and not tid):
                    try:
                        iid_key = int(iid) if iid is not None else int(tid)
                    except Exception:
                        iid_key = iid if iid is not None else tid
                    matched = rad_name_map.get((bno, iid_key)) or rad_name_map.get(iid_key)
                    name = matched[0] if matched else (it_c.get("test_name") or it_c.get("item_name") or "")
                    cat = matched[1] if matched else "Radiology"
                    it_c["test_name"] = name
                    it_c["item_name"] = name
                    it_c["department"] = cat
                elif tid is not None:
                    try:
                        tid_key = int(tid)
                    except Exception:
                        tid_key = tid
                    matched_lab = lab_test_map.get(tid_key)
                    name = matched_lab[0] if matched_lab else (it_c.get("test_name") or "")
                    dept = matched_lab[1] if matched_lab else (it_c.get("department") or "Diagnostics")
                    it_c["test_name"] = name
                    it_c["department"] = dept
                enriched_inv.append(it_c)
            consult_copy["investigation_details"] = enriched_inv

    return consult_copy



@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_DoctorConsultation(request):
    """
    GET: Retrieve doctor consultation records using OPDoctorConsultation model and OPDoctorConsultationSerializer.
    POST: Save or update doctor consultation record using OPDoctorConsultation model and OPDoctorConsultationSerializer.
    """
    try:
        if request.method == 'GET':
            uhid = request.query_params.get('uhid')
            consult_id = request.query_params.get('id') or request.query_params.get('_id') or request.query_params.get('consultation_id')

            qs = OPDoctorConsultation.objects.all()
            if uhid:
                qs = qs.filter(uhid=uhid)
            if consult_id:
                try:
                    qs = qs.filter(Q(_id=ObjectId(str(consult_id))) | Q(pk=ObjectId(str(consult_id))))
                except Exception:
                    qs = qs.filter(Q(_id=str(consult_id)) | Q(pk=str(consult_id)))

            qs = qs.order_by('-created_date', '-date')
            serializer = OPDoctorConsultationSerializer(qs, many=True)
            enriched_data = [enrich_consultation_investigation_names(c) for c in serializer.data]
            return Response(enriched_data, status=status.HTTP_200_OK)

        elif request.method == 'POST':
            data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
            uhid = data.get("uhid")
            if not uhid:
                return Response({"error": "uhid is required"}, status=status.HTTP_400_BAD_REQUEST)

            employee_id = data.get("auth-user-id")
            consult_id = data.get("id") or data.get("_id") or data.get("consultation_id")

            # Clean and prepare vitals
            vitals_data = data.get("vitals", {})
            if isinstance(vitals_data, dict):
                vitals_data.pop('_id', None)
                vitals_data.pop('id', None)
                vitals_data.pop('created_by_name', None)  # Do NOT store created_by name in vitals
                if not vitals_data.get("created_by"):
                    try:
                        v_obj = VitalEntry.objects.filter(uhid=uhid).order_by('-created_date').first()
                        if v_obj and v_obj.created_by:
                            vitals_data["created_by"] = str(v_obj.created_by)
                    except Exception:
                        pass
                if not vitals_data.get("created_by") and employee_id:
                    vitals_data["created_by"] = str(employee_id)
                data["vitals"] = vitals_data

            # Ensure ONLY billTypeNo and item_id are saved in ct_scan_details, mri_scan_details, xray_details, usg_details (NO NAMES STORED)
            def sanitize_rad_records(items, default_bno):
                if not isinstance(items, list):
                    return []
                clean_items = []
                for itm in items:
                    if isinstance(itm, dict):
                        b_no = str(itm.get("billTypeNo") or default_bno).strip()
                        i_id = itm.get("item_id")
                        if i_id is None:
                            i_id = itm.get("id") or itm.get("test_id")
                        try:
                            i_id = int(i_id)
                        except Exception:
                            pass
                        clean_items.append({
                            "billTypeNo": b_no,
                            "item_id": i_id
                        })
                    elif itm is not None:
                        try:
                            i_id = int(itm)
                        except Exception:
                            i_id = itm
                        clean_items.append({
                            "billTypeNo": default_bno,
                            "item_id": i_id
                        })
                return clean_items

            if "ct_scan_details" in data:
                data["ct_scan_details"] = sanitize_rad_records(data.get("ct_scan_details"), "CT01")
            if "mri_scan_details" in data:
                data["mri_scan_details"] = sanitize_rad_records(data.get("mri_scan_details"), "MRI01")
            if "xray_details" in data:
                data["xray_details"] = sanitize_rad_records(data.get("xray_details"), "XRAY01")
            if "usg_details" in data:
                data["usg_details"] = sanitize_rad_records(data.get("usg_details"), "USG01")

            # Ensure NO investigation names are stored in investigation_details
            if "investigation_details" in data:
                raw_inv = data.get("investigation_details")
                if isinstance(raw_inv, list):
                    clean_inv = []
                    for itm in raw_inv:
                        if isinstance(itm, dict):
                            entry = {}
                            if "billTypeNo" in itm:
                                entry["billTypeNo"] = str(itm["billTypeNo"]).strip()
                            if "item_id" in itm:
                                try:
                                    entry["item_id"] = int(itm["item_id"])
                                except Exception:
                                    entry["item_id"] = itm["item_id"]
                            if "test_id" in itm:
                                try:
                                    entry["test_id"] = int(itm["test_id"])
                                except Exception:
                                    entry["test_id"] = itm["test_id"]
                            # Explicitly drop test_name, item_name, name, department, MRP
                            if entry:
                                clean_inv.append(entry)
                        elif itm is not None:
                            try:
                                clean_inv.append({"test_id": int(itm)})
                            except Exception:
                                clean_inv.append({"test_id": itm})
                    data["investigation_details"] = clean_inv

            # Determine status
            new_status = data.get("status")
            if not new_status:
                new_status = "Completed" if data.get("consultation_end_time") else "In Progress"
            data["status"] = new_status

            # Handle start and end times
            consult_start = data.get("consultation_start_time")
            if consult_start in ["", "null"]:
                data["consultation_start_time"] = None

            consult_end = data.get("consultation_end_time")
            if consult_end in ["", "null"]:
                data["consultation_end_time"] = None

            today_start = now().replace(hour=0, minute=0, second=0, microsecond=0)
            doc_id_val = str(data.get("doctor_id") or employee_id or "").strip()

            # 1. Try finding existing consultation document by id
            existing_consult = None
            if consult_id:
                try:
                    existing_consult = OPDoctorConsultation.objects.filter(
                        Q(_id=ObjectId(str(consult_id))) | Q(pk=ObjectId(str(consult_id)))
                    ).first()
                except Exception:
                    existing_consult = OPDoctorConsultation.objects.filter(
                        Q(_id=str(consult_id)) | Q(pk=str(consult_id))
                    ).first()

            # 2. If not found by id, find consultation for this patient created today for this doctor
            if not existing_consult and uhid:
                doc_query = Q(uhid=uhid, created_date__gte=today_start)
                if doc_id_val:
                    doc_query &= (Q(doctor_id=doc_id_val) | Q(created_by=doc_id_val))
                existing_consult = OPDoctorConsultation.objects.filter(doc_query).order_by('-created_date').first()

            # 3. Fallback: find any consultation for this patient created today
            if not existing_consult and uhid:
                existing_consult = OPDoctorConsultation.objects.filter(
                    uhid=uhid, created_date__gte=today_start
                ).order_by('-created_date').first()

            if existing_consult:
                # Update existing consultation document
                data["lastmodified_by"] = employee_id
                data["lastmodified_date"] = now()
                if not data.get("doctor_id") and existing_consult.doctor_id:
                    data["doctor_id"] = existing_consult.doctor_id

                if not data.get("consultation_start_time"):
                    data["consultation_start_time"] = existing_consult.consultation_start_time or existing_consult.created_date or now()

                if not data.get("consultation_end_time"):
                    if new_status == "Completed":
                        data["consultation_end_time"] = existing_consult.consultation_end_time or now()

                serializer = OPDoctorConsultationSerializer(existing_consult, data=data, partial=True)
                is_update = True
            else:
                # Create new consultation document
                data["created_by"] = employee_id
                data["created_date"] = now()
                data["lastmodified_by"] = None
                data["lastmodified_date"] = None
                if not data.get("doctor_id"):
                    data["doctor_id"] = doc_id_val
                if not data.get("consultation_start_time"):
                    data["consultation_start_time"] = now()
                if new_status == "Completed" and not data.get("consultation_end_time"):
                    data["consultation_end_time"] = now()

                serializer = OPDoctorConsultationSerializer(data=data)
                is_update = False

            if serializer.is_valid():
                saved_consult = serializer.save()

                # Sync Billing consultation_status if completed
                if uhid and (new_status == "Completed" or data.get("consultation_end_time")):
                    try:
                        p_obj = Patient.objects.filter(uhid=uhid).first()
                        if p_obj:
                            for b in Billing.objects.filter(patient=p_obj):
                                b.consultation_status = 'Completed'
                                b.save(update_fields=['consultation_status'])
                    except Exception as b_err:
                        print("Error updating Billing status:", b_err)

                return Response(
                    {
                        "message": "Doctor consultation saved successfully.",
                        "data": OPDoctorConsultationSerializer(saved_consult).data
                    },
                    status=status.HTTP_200_OK if is_update else status.HTTP_201_CREATED
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
@permission_classes([HasRoleAndDataPermission])
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
@permission_classes([HasRoleAndDataPermission])
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
@permission_classes([HasRoleAndDataPermission])
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
@permission_classes([HasRoleAndDataPermission])
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

        data = request.data or {}
        employee_id = (
            data.get("auth-user-id")
            or request.query_params.get("doctor_id")
            or request.query_params.get("doctor")
            or request.headers.get("auth-user-id")
            or request.headers.get("doctor_id")
        )
        print("employee_id in OPEMR_get_Doctor_patient:", employee_id)

        if not employee_id:
            return Response([], status=status.HTTP_200_OK)

        emp_str = str(employee_id).strip()
        possible_ids = {emp_str}
        if emp_str.isdigit():
            num = int(emp_str)
            possible_ids.add(str(num))
            possible_ids.add(num)
            possible_ids.add(f"{num:04d}")
            possible_ids.add(f"{num:05d}")
            possible_ids.add(f"{num:06d}")

        doctor_queries = Q(doctor_id__in=list(possible_ids))

        # Check for patients referred to this doctor in OPDoctorConsultation (refer_to_doctor)
        referral_queries = Q(refer_to_doctor__in=list(possible_ids))
        referred_consults = OPDoctorConsultation.objects.filter(referral_queries).order_by('-created_date')

        referred_uhid_map = {}
        for rc in referred_consults:
            u = getattr(rc, 'uhid', '')
            if u:
                u_str = str(u).strip()
                if u_str not in referred_uhid_map:
                    referred_uhid_map[u_str] = rc

        bill_filter = doctor_queries
        if referred_uhid_map:
            bill_filter |= Q(patient__uhid__in=list(referred_uhid_map.keys()))

        paid_bills = Billing.objects.filter(
            payment_status__in=['Paid', 'paid', 'Pending', 'pending', 'Unpaid', 'unpaid']
        ).filter(bill_filter).select_related('patient').order_by('-billed_date')

        result = []
        seen_uhids = set()
        from hospital.Views.dbcollection import get_employee_name_by_id

        for bill in paid_bills:
            patient_obj = getattr(bill, 'patient', None)
            if not patient_obj:
                continue

            uhid_str = getattr(patient_obj, 'uhid', '') or ''
            if uhid_str and uhid_str in seen_uhids:
                continue
            if uhid_str:
                seen_uhids.add(uhid_str)

            salutation = getattr(patient_obj, 'salutation', '') or ''
            first_name = getattr(patient_obj, 'firstName', '') or ''
            last_name = getattr(patient_obj, 'lastName', '') or ''
            full_name = f"{salutation} {first_name} {last_name}".strip()

            bill_doctor_id = getattr(bill, 'doctor_id', '') or ''
            bill_doctor_name = get_employee_name_by_id(bill_doctor_id)

            is_referred = uhid_str in referred_uhid_map
            ref_consult = referred_uhid_map.get(uhid_str)
            ref_creator_id = ""
            referred_from_name = ""
            if ref_consult:
                # Use created_by as the referring doctor ID
                ref_creator_id = getattr(ref_consult, 'created_by', None) or getattr(ref_consult, 'doctor_id', None) or ""
                referred_from_name = get_employee_name_by_id(ref_creator_id)
                if not referred_from_name or referred_from_name == "Unknown":
                    doc_id_val = getattr(ref_consult, 'doctor_id', None)
                    if doc_id_val and str(doc_id_val) != str(ref_creator_id):
                        referred_from_name = get_employee_name_by_id(doc_id_val)
                if not referred_from_name or referred_from_name == "Unknown":
                    referred_from_name = bill_doctor_name if bill_doctor_name != "Unknown" else str(ref_creator_id)

            patient_data = {
                "id": getattr(patient_obj, 'id', None),
                "uhid": uhid_str,
                "salutation": salutation,
                "firstName": first_name,
                "lastName": last_name,
                "patient_name": full_name or f"Patient ({uhid_str})",
                "age": getattr(patient_obj, 'age', None),
                "gender": getattr(patient_obj, 'gender', '') or '',
                "dob": str(patient_obj.dob) if getattr(patient_obj, 'dob', None) else '',
                "mobilePhone": getattr(patient_obj, 'mobilePhone', '') or '',
                "blood_group": getattr(patient_obj, 'blood_group', '') or '',
                "city": getattr(patient_obj, 'city', '') or '',
                "permanent_address": getattr(patient_obj, 'permanent_address', '') or '',
                "doctorName": get_employee_name_by_id(emp_str) if is_referred else bill_doctor_name,
                "emergency_contact": getattr(patient_obj, 'emergency_contact', '') or '',
            }

            billed_d = getattr(bill, 'billed_date', None)
            billed_date_str = safe_isoformat(billed_d) or ""

            latest_vital = None
            is_completed_today = False
            if uhid_str:
                vital_entries = list(VitalEntry.objects.filter(uhid=uhid_str).order_by('-created_date')[:1])
                vital_entry_obj = vital_entries[0] if vital_entries else None
                if vital_entry_obj:
                    latest_vital = VitalEntrySerializer(vital_entry_obj).data
                    if getattr(vital_entry_obj, 'created_date', None):
                        from django.utils import timezone
                        if vital_entry_obj.created_date.date() == timezone.now().date():
                            is_completed_today = True

            latest_consult = None
            is_consultation_completed_today = False
            consult_time_str = None
            if uhid_str:
                doc_consult_filter = Q(uhid=uhid_str) & (Q(doctor_id__in=list(possible_ids)) | Q(created_by__in=list(possible_ids)))
                consult_entries = list(OPDoctorConsultation.objects.filter(doc_consult_filter))
                if consult_entries:
                    from django.utils import timezone
                    today_d = timezone.localdate()

                    def is_consult_today(c):
                        for f in ['created_date', 'date', 'lastmodified_date', 'consultation_end_time', 'consultation_start_time']:
                            dt = getattr(c, f, None)
                            if not dt:
                                continue
                            if hasattr(dt, 'date'):
                                try:
                                    c_d = timezone.localdate(dt) if timezone.is_aware(dt) else dt.date()
                                    if c_d == today_d:
                                        return True
                                except Exception:
                                    if dt.date() == today_d:
                                        return True
                            elif isinstance(dt, str):
                                if str(today_d) in dt[:10]:
                                    return True
                        return False

                    def consult_rank(c):
                        is_done = 1 if (getattr(c, 'consultation_end_time', None) or getattr(c, 'status', '') == 'Completed') else 0
                        is_tod = 1 if is_consult_today(c) else 0
                        ts = getattr(c, 'lastmodified_date', None) or getattr(c, 'consultation_end_time', None) or getattr(c, 'created_date', None) or getattr(c, 'date', None)
                        ts_val = ts.timestamp() if (ts and hasattr(ts, 'timestamp')) else 0
                        return (is_tod, is_done, ts_val)

                    consult_entries.sort(key=consult_rank, reverse=True)
                    consult_obj = consult_entries[0]
                    c_start = getattr(consult_obj, 'consultation_start_time', None) or getattr(consult_obj, 'created_date', None) or getattr(consult_obj, 'date', None)

                    if is_consult_today(consult_obj):
                        latest_consult = enrich_consultation_investigation_names(OPDoctorConsultationSerializer(consult_obj).data)
                        consult_time_str = safe_isoformat(c_start)

                    if any((getattr(c, 'consultation_end_time', None) or getattr(c, 'status', '') == 'Completed') for c in consult_entries if is_consult_today(c)):
                        is_consultation_completed_today = True

            if getattr(bill, 'consultation_status', '') == 'Completed':
                if not consult_entries or not is_consultation_completed_today:
                    # No active completed consultation document exists in hospital_opdoctorconsultation; sync bill status
                    new_bill_status = 'Ready' if is_completed_today else 'Waiting'
                    try:
                        bill.consultation_status = new_bill_status
                        bill.save(update_fields=['consultation_status'])
                    except Exception:
                        pass
                else:
                    is_consultation_completed_today = True

            if is_consultation_completed_today:
                overall_status = "Completed"
            elif latest_consult and getattr(consult_obj, 'consultation_start_time', None):
                overall_status = "In Consultation"
            elif is_completed_today:
                overall_status = "Ready"
            else:
                overall_status = "Waiting"

            result.append({
                "bill_number": getattr(bill, 'bill_number', ''),
                "billed_date": billed_date_str,
                "payment_status": getattr(bill, 'payment_status', 'Paid'),
                "total_fees": safe_float(getattr(bill, 'total_fees', None)),
                "registration_fee": safe_float(getattr(bill, 'registration_fee', None)),
                "consulting_fee": safe_float(getattr(bill, 'consulting_fee', None)),
                "payment_method": getattr(bill, 'payment_method', '') or '',
                "doctor_id": emp_str if is_referred else bill_doctor_id,
                "patient": patient_data,
                "vital_entry": latest_vital,
                "vital_status": "Completed" if is_completed_today else "Pending",
                "consultation": latest_consult,
                "consultation_status": overall_status,
                "is_consultation_completed": is_consultation_completed_today,
                "consultation_time": consult_time_str,
                "is_referred": is_referred,
                "referred_from": referred_from_name if is_referred else None,
                "refer_from": referred_from_name if is_referred else None,
                "referred_from_doctor": referred_from_name if is_referred else None,
                "referred_from_id": str(ref_creator_id) if is_referred else None,
                "refer_to_doctor": getattr(ref_consult, 'refer_to_doctor', '') if is_referred else None
            })

        # Add any referred patients who do not have an active billing record
        for ref_u, ref_c in referred_uhid_map.items():
            if ref_u in seen_uhids:
                continue
            patient_obj = Patient.objects.filter(uhid=ref_u).first()
            if not patient_obj:
                continue
            seen_uhids.add(ref_u)

            salutation = getattr(patient_obj, 'salutation', '') or ''
            first_name = getattr(patient_obj, 'firstName', '') or ''
            last_name = getattr(patient_obj, 'lastName', '') or ''
            full_name = f"{salutation} {first_name} {last_name}".strip()

            ref_creator_id = getattr(ref_c, 'created_by', None) or getattr(ref_c, 'doctor_id', None) or ""
            referred_from_name = get_employee_name_by_id(ref_creator_id)
            if not referred_from_name or referred_from_name == "Unknown":
                doc_id_val = getattr(ref_c, 'doctor_id', None)
                if doc_id_val and str(doc_id_val) != str(ref_creator_id):
                    referred_from_name = get_employee_name_by_id(doc_id_val)
            if not referred_from_name or referred_from_name == "Unknown":
                referred_from_name = str(ref_creator_id)

            patient_data = {
                "id": getattr(patient_obj, 'id', None),
                "uhid": ref_u,
                "salutation": salutation,
                "firstName": first_name,
                "lastName": last_name,
                "patient_name": full_name or f"Patient ({ref_u})",
                "age": getattr(patient_obj, 'age', None),
                "gender": getattr(patient_obj, 'gender', '') or '',
                "dob": str(patient_obj.dob) if getattr(patient_obj, 'dob', None) else '',
                "mobilePhone": getattr(patient_obj, 'mobilePhone', '') or '',
                "blood_group": getattr(patient_obj, 'blood_group', '') or '',
                "city": getattr(patient_obj, 'city', '') or '',
                "permanent_address": getattr(patient_obj, 'permanent_address', '') or '',
                "doctorName": get_employee_name_by_id(emp_str),
                "emergency_contact": getattr(patient_obj, 'emergency_contact', '') or '',
            }

            ref_date = getattr(ref_c, 'created_date', None) or getattr(ref_c, 'date', None)

            latest_vital = None
            is_completed_today = False
            vital_entries = list(VitalEntry.objects.filter(uhid=ref_u).order_by('-created_date')[:1])
            vital_entry_obj = vital_entries[0] if vital_entries else None
            if vital_entry_obj:
                latest_vital = VitalEntrySerializer(vital_entry_obj).data
                if getattr(vital_entry_obj, 'created_date', None):
                    from django.utils import timezone
                    if vital_entry_obj.created_date.date() == timezone.now().date():
                        is_completed_today = True

            latest_consult = None
            is_consultation_completed_today = False
            consult_time_str = None
            doc_consult_filter = Q(uhid=ref_u) & (Q(doctor_id__in=list(possible_ids)) | Q(created_by__in=list(possible_ids)))
            consult_entries = list(OPDoctorConsultation.objects.filter(doc_consult_filter))
            if consult_entries:
                from django.utils import timezone
                today_d = timezone.localdate()

                def is_consult_today_ref(c):
                    for f in ['created_date', 'date', 'lastmodified_date', 'consultation_end_time', 'consultation_start_time']:
                        dt = getattr(c, f, None)
                        if not dt:
                            continue
                        if hasattr(dt, 'date'):
                            try:
                                c_d = timezone.localdate(dt) if timezone.is_aware(dt) else dt.date()
                                if c_d == today_d:
                                    return True
                            except Exception:
                                if dt.date() == today_d:
                                    return True
                        elif isinstance(dt, str):
                            if str(today_d) in dt[:10]:
                                return True
                    return False

                def consult_rank_ref(c):
                    is_done = 1 if (getattr(c, 'consultation_end_time', None) or getattr(c, 'status', '') == 'Completed') else 0
                    is_tod = 1 if is_consult_today_ref(c) else 0
                    ts = getattr(c, 'lastmodified_date', None) or getattr(c, 'consultation_end_time', None) or getattr(c, 'created_date', None) or getattr(c, 'date', None)
                    ts_val = ts.timestamp() if (ts and hasattr(ts, 'timestamp')) else 0
                    return (is_tod, is_done, ts_val)

                consult_entries.sort(key=consult_rank_ref, reverse=True)
                consult_obj = consult_entries[0]
                c_start = getattr(consult_obj, 'consultation_start_time', None) or getattr(consult_obj, 'created_date', None) or getattr(consult_obj, 'date', None)

                if is_consult_today_ref(consult_obj):
                    latest_consult = enrich_consultation_investigation_names(OPDoctorConsultationSerializer(consult_obj).data)
                    consult_time_str = safe_isoformat(c_start)

                if any((getattr(c, 'consultation_end_time', None) or getattr(c, 'status', '') == 'Completed') for c in consult_entries if is_consult_today_ref(c)):
                    is_consultation_completed_today = True

            if is_consultation_completed_today:
                overall_status = "Completed"
            elif latest_consult and getattr(consult_obj, 'consultation_start_time', None):
                overall_status = "In Consultation"
            elif is_completed_today:
                overall_status = "Ready"
            else:
                overall_status = "Waiting"

            result.append({
                "bill_number": "REFERRED",
                "billed_date": safe_isoformat(ref_date) or "",
                "payment_status": "Paid",
                "total_fees": 0.0,
                "registration_fee": 0.0,
                "consulting_fee": 0.0,
                "payment_method": "Referral",
                "doctor_id": emp_str,
                "patient": patient_data,
                "vital_entry": latest_vital,
                "vital_status": "Completed" if is_completed_today else "Pending",
                "consultation": latest_consult,
                "consultation_status": overall_status,
                "is_consultation_completed": is_consultation_completed_today,
                "consultation_time": consult_time_str,
                "is_referred": True,
                "referred_from": referred_from_name,
                "refer_from": referred_from_name,
                "referred_from_doctor": referred_from_name,
                "referred_from_id": str(ref_creator_id),
                "refer_to_doctor": getattr(ref_c, 'refer_to_doctor', '')
            })

        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_get_patient_lab_results(request):
    """
    Retrieve diagnostic test results for a patient from Diagnostics.core_testvalue & core_mbtestvalue (same as discharge summary).
    Query parameter: ?uhid=...
    """
    try:
        uhid = (request.query_params.get('uhid') or request.GET.get('uhid') or '').strip()
        if not uhid:
            return Response([], status=status.HTTP_200_OK)

        if Diagnostics_db is None:
            return Response([], status=status.HTTP_200_OK)

        core_hmsbarcode = Diagnostics_db["core_hmsbarcode"]
        core_testvalue = Diagnostics_db["core_testvalue"]
        core_mbtestvalue = Diagnostics_db["core_mbtestvalue"]
        core_testdetails = Diagnostics_db["core_testdetails"]
        invest_coll = hms_db["hospital_investbilling"] if hms_db is not None else None

        # 1. Match barcodes by UHID in core_hmsbarcode and invest bills
        barcode_query = [
            {"patient_id": uhid},
            {"patient_id": {"$regex": f"^{re.escape(uhid)}$", "$options": "i"}}
        ]

        if invest_coll is not None:
            invest_bills = list(invest_coll.find(
                {"$or": [{"uhid": uhid}, {"uhid": {"$regex": f"^{re.escape(uhid)}$", "$options": "i"}}]},
                {"investBillNo": 1, "billNumber": 1, "_id": 0}
            ))
            bill_numbers = [b.get("investBillNo") or b.get("billNumber") for b in invest_bills if b.get("investBillNo") or b.get("billNumber")]
            if bill_numbers:
                barcode_query.append({"billnumber": {"$in": bill_numbers}})

        barcode_records = list(core_hmsbarcode.find({"$or": barcode_query}))
        found_barcodes = list(set([b.get("barcode") for b in barcode_records if b.get("barcode")]))

        # Helper: get parameter definition from core_testdetails
        def get_parameter_from_core(core_test, device_id, test_code=None, param_index=None):
            if not core_test:
                return None
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

        lab_results = []

        # 2. Fetch from core_testvalue
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
                    dispatch_time = test.get("dispatch_time", "")
                    comment = test.get("comment", "")
                    remarks = test.get("remarks", "")
                    is_approved = bool(test.get("approve") is True)

                    core_test = core_testdetails.find_one({"test_id": test_id}) if test_id else None
                    testname = core_test.get("test_name") if core_test else test.get("testname", "Diagnostic Test")
                    department = core_test.get("department") if core_test else test.get("department", "Diagnostics")
                    specimen_type = core_test.get("specimen_type") if core_test else test.get("specimen_type", "")
                    nabl = bool(core_test.get("NABL", False)) if core_test else False

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
                    elif test.get("value") is not None and str(test.get("value")).strip() != "":
                        val = str(test.get("value")).strip()
                        t_code = test.get("test_code")
                        p_def = get_parameter_from_core(core_test, device_id, test_code=t_code, param_index=0) if core_test else None
                        param_name = (p_def.get("test_name") if p_def else None) or testname
                        unit = (p_def.get("unit") if p_def else None) or (core_test.get("unit") if core_test else "") or ""
                        ref_range = (p_def.get("reference_range") if p_def else None) or (core_test.get("reference_range") if core_test else "") or ""
                        method = (p_def.get("method") if p_def else None) or (core_test.get("method") if core_test else "") or ""
                        parsed_params.append({
                            "name": param_name,
                            "test_code": t_code or "",
                            "value": val,
                            "unit": unit,
                            "reference_range": ref_range,
                            "method": method,
                            "comment": test.get("comment", "")
                        })

                    lab_results.append({
                        "barcode": bc,
                        "test_id": test_id,
                        "testname": testname,
                        "department": department,
                        "specimen_type": specimen_type,
                        "NABL": nabl,
                        "parameters": parsed_params,
                        "approve_by": approve_by,
                        "approve_time": approve_time,
                        "dispatch_time": dispatch_time,
                        "verified_by": verified_by,
                        "is_approved": is_approved,
                        "comment": comment,
                        "remarks": remarks,
                        "is_microbiology": False
                    })

        # 3. Fetch from core_mbtestvalue (microbiology)
        if core_mbtestvalue is not None:
            for bc in found_barcodes:
                mb_records = list(core_mbtestvalue.find({"barcode": bc}))
                for mb in mb_records:
                    raw = mb.get("testdetails", "[]")
                    details = json.loads(raw) if isinstance(raw, str) else (raw or [])
                    if not isinstance(details, list):
                        continue
                    for test in details:
                        test_id = test.get("test_id")
                        core_test = core_testdetails.find_one({"test_id": test_id}) if test_id else None
                        testname = core_test.get("test_name") if core_test else test.get("testname", "Microbiology Test")
                        department = core_test.get("department") if core_test else "Microbiology"
                        lab_results.append({
                            "barcode": bc,
                            "test_id": test_id,
                            "testname": testname,
                            "department": department,
                            "specimen_type": test.get("specimen_type", "Specimen"),
                            "parameters": test.get("parameters", []),
                            "approve_by": test.get("approve_by", ""),
                            "approve_time": test.get("approve_time", "N/A"),
                            "is_approved": bool(test.get("approve") is True),
                            "comment": test.get("comment", ""),
                            "remarks": test.get("remarks", ""),
                            "is_microbiology": True
                        })

        # Sort with most recent approve_time first
        lab_results.sort(key=lambda x: str(x.get("approve_time") or ""), reverse=True)
        return Response(lab_results, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def OPEMR_get_patient_discharge_summaries(request):
    """
    Fetches all discharge summaries for a given patient UHID, grouped/admission-wise.
    Enriches with summaryType, heading, and patient info for displaying in Patient Past History modal.
    """
    uhid = request.query_params.get("uhid", "").strip()
    if not uhid:
        return Response({"success": False, "message": "UHID is required", "data": []}, status=status.HTTP_400_BAD_REQUEST)

    try:
        from hospital.Views.dbcollection import hms_db
        summary_coll = hms_db['hospital_summary']
        patient_coll = hms_db['hospital_patient']
        summary_type_coll = hms_db['hospital_summarytype']
        summary_heading_coll = hms_db['hospital_summaryheading']

        # Find summaries by exact UHID or regex
        cursor = summary_coll.find({"uhid": uhid, "is_active": {"$ne": False}})
        summaries = list(cursor)
        if not summaries:
            cursor = summary_coll.find({"uhid": {"$regex": f"^{re.escape(uhid)}$", "$options": "i"}, "is_active": {"$ne": False}})
            summaries = list(cursor)

        # Preload masters
        types_map = {str(t.get('summaryNo')): t.get('summaryType') for t in summary_type_coll.find({}, {"summaryNo": 1, "summaryType": 1})}
        headings_map = {str(h.get('headingNo')): h.get('heading') for h in summary_heading_coll.find({}, {"headingNo": 1, "heading": 1})}

        # Patient demographic info
        patient_doc = patient_coll.find_one({"uhid": uhid}) or {}

        results = []
        for s in summaries:
            s_copy = dict(s)
            s_copy["_id"] = str(s_copy.get("_id", ""))
            s_no = str(s_copy.get("summaryNo") or "").strip()
            h_no = str(s_copy.get("headingNo") or "").strip()
            s_copy["summaryType"] = types_map.get(s_no) or s_copy.get("summaryType") or "Discharge Summary"
            s_copy["heading"] = headings_map.get(h_no) or s_copy.get("heading") or ""

            # Stringify dates
            for dt_f in ["date", "doa", "dod", "created_date", "lastmodified_date", "approve_time", "nextReviewDate", "surgeryDate"]:
                if s_copy.get(dt_f):
                    s_copy[dt_f] = str(s_copy[dt_f])

            # Standardize fieldsData as list of {key, value}
            raw_fields = s_copy.get("fieldsData")
            if isinstance(raw_fields, str):
                try:
                    s_copy["fieldsData"] = json.loads(raw_fields)
                except Exception:
                    s_copy["fieldsData"] = []
            elif isinstance(raw_fields, dict):
                s_copy["fieldsData"] = [{"key": k, "value": v} for k, v in raw_fields.items()]
            elif not isinstance(raw_fields, list):
                s_copy["fieldsData"] = []

            # Patient details fallback
            s_copy["patient_name"] = patient_doc.get("patient_name") or patient_doc.get("name") or s_copy.get("patient") or ""
            s_copy["age"] = patient_doc.get("age") or s_copy.get("age") or ""
            s_copy["gender"] = patient_doc.get("gender") or s_copy.get("gender") or ""
            s_copy["mobilePhone"] = patient_doc.get("mobilePhone") or patient_doc.get("mobile_number") or s_copy.get("mobilePhone") or ""
            s_copy["address"] = patient_doc.get("address") or s_copy.get("address") or ""

            results.append(s_copy)

        # Sort admission-wise by DOA descending, then date descending
        results.sort(key=lambda x: str(x.get("doa") or x.get("date") or ""), reverse=True)

        return Response({"success": True, "data": results, "count": len(results)}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



