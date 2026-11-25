from pydoc import doc

from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from ..models import Patient,EstimateBilling,Admission, InsuranceProvider
from ..serializers import PatientSerializer,EstimateBillingSerializer
from rest_framework import status
from pymongo import MongoClient  
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime, timezone as py_timezone, timedelta as py_timedelta
from django.http import JsonResponse
from bson import ObjectId
from rest_framework import status as drf_status
import os, json
import traceback
from django.utils import timezone
from django.db.models import Q
from django.db import connection
from bson import Decimal128, ObjectId
from bson.json_util import dumps
import json
from pymongo import MongoClient, ReturnDocument
import re

IST = py_timezone(py_timedelta(hours=5, minutes=30))

def _parse_ist_date_bound(date_str, is_end=False):
    """
    Convert a YYYY-MM-DD date string (assumed to be in IST) to a UTC naive datetime.
    If is_end is False: returns the start of the day in IST (00:00:00) converted to UTC.
    If is_end is True:  returns the end of the day in IST (23:59:59.999999) converted to UTC.
    """
    dt = datetime.strptime(str(date_str).strip()[:10], "%Y-%m-%d")
    if is_end:
        dt_ist = dt.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=IST)
    else:
        dt_ist = dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=IST)
    return dt_ist.astimezone(py_timezone.utc).replace(tzinfo=None)



def _build_uhid_search_query(uhid_str):
    clean = str(uhid_str or '').strip()
    if not clean:
        return Q()
    if '/' in clean:
        parts = clean.split('/', 1)
        prefix, num_part = parts[0].strip(), parts[1].strip()
        if num_part.isdigit():
            num_int = int(num_part)
            p6 = str(num_int).zfill(6)
            p5 = str(num_int).zfill(5)
            if prefix:
                return (
                    Q(uhid__iexact=f'{prefix}/{p6}') |
                    Q(uhid__iexact=f'{prefix}/{p5}') |
                    Q(uhid__iexact=f'{prefix}/{num_part}') |
                    Q(uhid__iexact=clean)
                )
            else:
                return (
                    Q(uhid__iendswith=f'/{p6}') |
                    Q(uhid__iendswith=f'/{p5}') |
                    Q(uhid__iendswith=f'/{num_part}')
                )
        elif prefix:
            return Q(uhid__istartswith=f'{prefix}/')
        else:
            return Q(uhid__iexact=clean)
    elif clean.isdigit():
        num_int = int(clean)
        p6 = str(num_int).zfill(6)
        p5 = str(num_int).zfill(5)
        return (
            Q(uhid__iendswith=f'/{p6}') |
            Q(uhid__iendswith=f'/{p5}') |
            Q(uhid__iexact=clean)
        )
    else:
        return (
            Q(uhid__istartswith=f'{clean}/') |
            Q(uhid__istartswith=clean) |
            Q(uhid__iexact=clean)
        )


def _build_ip_search_query(ip_str):
    clean = str(ip_str or '').strip()
    if not clean:
        return Q()
    if '/' in clean:
        parts = clean.split('/', 1)
        prefix, num_part = parts[0].strip(), parts[1].strip()
        if num_part.isdigit():
            num_int = int(num_part)
            p6 = str(num_int).zfill(6)
            p5 = str(num_int).zfill(5)
            if prefix:
                return (
                    Q(ipNumber__iexact=f'{prefix}/{p6}') |
                    Q(ipNumber__iexact=f'{prefix}/{p5}') |
                    Q(ipNumber__iexact=f'{prefix}/{num_part}') |
                    Q(ipNumber__iexact=clean)
                )
            else:
                return (
                    Q(ipNumber__iendswith=f'/{p6}') |
                    Q(ipNumber__iendswith=f'/{p5}') |
                    Q(ipNumber__iendswith=f'/{num_part}')
                )
        elif prefix:
            return Q(ipNumber__istartswith=f'{prefix}/')
        else:
            return Q(ipNumber__iexact=clean)
    elif clean.isdigit():
        num_int = int(clean)
        p6 = str(num_int).zfill(6)
        p5 = str(num_int).zfill(5)
        return (
            Q(ipNumber__iendswith=f'/{p6}') |
            Q(ipNumber__iendswith=f'/{p5}') |
            Q(ipNumber__iexact=clean)
        )
    else:
        return (
            Q(ipNumber__istartswith=f'{clean}/') |
            Q(ipNumber__istartswith=clean) |
            Q(ipNumber__iexact=clean)
        )


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def op_patient_detail_by_uhid(request, uhid):
    try:
        branch_code = request.data.get('auth-branch-code')
        hospital_code = request.data.get('auth-hospital-code')

        is_search = request.GET.get('search') == '1' or str(uhid).lower() == 'search'
        uhid_param = request.GET.get('uhid') or ('' if str(uhid).lower() == 'search' else str(uhid))
        name_param = (request.GET.get('name') or '').strip()
        mobile_param = (request.GET.get('mobile') or '').strip()
        admitted_filter = request.GET.get('admitted') == 'true' or request.GET.get('admitted') == '1'

        if is_search or name_param or mobile_param:
            query = Q()
            if uhid_param:
                query &= _build_uhid_search_query(uhid_param)

            if name_param:
                query &= (
                    Q(firstName__icontains=name_param) |
                    Q(lastName__icontains=name_param) |
                    Q(mobilePhone__icontains=name_param)
                )
            elif mobile_param:
                query &= Q(mobilePhone__icontains=mobile_param)

            if hospital_code and hospital_code != "system":
                query &= Q(hospital_code=hospital_code)
            if branch_code and branch_code != "system":
                query &= Q(branch_code=branch_code)

            order_fields = ('-uhid', '-created_date') if uhid_param else ('-created_date',)
            patients = list(Patient.objects.filter(query).order_by(*order_fields)[:100])
            patient_serializer = PatientSerializer(patients, many=True)
            patient_data = patient_serializer.data

            uhid_list = [str(p.get("uhid") or "").strip() for p in patient_data if p.get("uhid")]
            active_admissions = {}
            active_admissions_doc = {}
            if uhid_list:
                try:
                    adm_qs = Admission.objects.filter(uhid__in=uhid_list)
                    for adm in adm_qs:
                        adm_is_admitted = bool(getattr(adm, 'is_admitted', False))
                        adm_is_discharged = bool(getattr(adm, 'is_discharged', False))
                        adm_is_cancelled = bool(getattr(adm, 'is_cancelled', False))
                        if adm_is_admitted and not adm_is_discharged and not adm_is_cancelled:
                            u_key = str(adm.uhid or "").strip()
                            active_admissions[u_key] = adm.ipNumber
                            active_admissions[u_key.upper()] = adm.ipNumber
                            adm_doc = getattr(adm, 'admittingDoctor', '') or ''
                            active_admissions_doc[u_key] = adm_doc
                            active_admissions_doc[u_key.upper()] = adm_doc
                except Exception as ex:
                    print("Admission check error:", ex)

            company_codes = list({p.get('company_code') for p in patient_data if p.get('company_code')})
            insurance_map = {}
            if company_codes:
                try:
                    for ins in InsuranceProvider.objects.filter(company_code__in=company_codes):
                        insurance_map[ins.company_code] = ins.company_name
                except Exception:
                    pass

            for p in patient_data:
                p_uhid = str(p.get("uhid") or "").strip()
                if p_uhid in active_admissions or p_uhid.upper() in active_admissions:
                    ip_no = active_admissions.get(p_uhid) or active_admissions.get(p_uhid.upper())
                    adm_doc = active_admissions_doc.get(p_uhid) or active_admissions_doc.get(p_uhid.upper()) or ""
                    p["ip_number"] = ip_no
                    p["ipNumber"] = ip_no
                    p["admittingDoctor"] = adm_doc
                    p["admitted"] = True
                    p["is_admitted"] = True
                    p["is_discharged"] = False
                else:
                    p["admitted"] = False
                    p["is_admitted"] = False
                    p["is_discharged"] = True

                cc = (p.get('company_code') or '').strip()
                if cc and cc in insurance_map:
                    p['company_name'] = insurance_map[cc]

            if admitted_filter:
                patient_data = [p for p in patient_data if p.get('admitted')]

            return Response({
                "success": True,
                "data": patient_data,
                "results": patient_data
            }, status=200)

        # Direct single lookup
        query = {}
        if hospital_code and hospital_code != "system":
            query["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            query["branch_code"] = branch_code

        query["uhid"] = str(uhid)

        patient = Patient.objects.filter(**query).first()
        if not patient:
            u_clean = str(uhid).strip()
            fallback_q = _build_uhid_search_query(u_clean)
            if hospital_code and hospital_code != "system":
                fallback_q &= Q(hospital_code=hospital_code)
            if branch_code and branch_code != "system":
                fallback_q &= Q(branch_code=branch_code)
            patient = Patient.objects.filter(fallback_q).order_by('-uhid').first()

        if not patient:
            return Response({"error": "Patient not found"}, status=404)

        serializer = PatientSerializer(patient)
        data = dict(serializer.data)

        company_code = (data.get('company_code') or "").strip()
        if company_code:
            insurance = InsuranceProvider.objects.filter(company_code=company_code).first()
            data['company_name'] = insurance.company_name if insurance else None
        else:
            data['company_name'] = None

        return Response(data)

    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def ip_patient_detail_by_ipNumber(request, ipNumber):
    try:
        branch_code = request.data.get('auth-branch-code')
        hospital_code = request.data.get('auth-hospital-code')

        is_search = request.GET.get('search') == '1' or str(ipNumber).lower() == 'search'
        ip_param = request.GET.get('ip_number') or ('' if str(ipNumber).lower() == 'search' else str(ipNumber))
        name_param = (request.GET.get('name') or '').strip()

        if is_search or name_param:
            query = Q()
            if ip_param:
                query &= _build_ip_search_query(ip_param)

            if hospital_code and hospital_code != "system":
                query &= Q(hospital_code=hospital_code)
            if branch_code and branch_code != "system":
                query &= Q(branch_code=branch_code)

            order_fields = ('-ipNumber', '-created_date') if ip_param else ('-created_date',)
            admissions = list(Admission.objects.filter(query).order_by(*order_fields)[:100])
            adm_uhids = [a.uhid for a in admissions if a.uhid]
            patients_map = {}
            if adm_uhids:
                p_qs = Patient.objects.filter(uhid__in=adm_uhids)
                for p in p_qs:
                    patients_map[p.uhid] = p

            company_codes = list({
                (adm.company_code or getattr(pt, 'company_code', '') or '').strip()
                for adm in admissions
                for pt in [patients_map.get(adm.uhid)]
                if pt and (adm.company_code or getattr(pt, 'company_code', None))
            })
            company_codes = [c for c in company_codes if c]
            insurance_map = {}
            if company_codes:
                try:
                    for ins in InsuranceProvider.objects.filter(company_code__in=company_codes):
                        insurance_map[ins.company_code] = ins.company_name
                except Exception:
                    pass

            results_list = []
            for adm in admissions:
                pt = patients_map.get(adm.uhid)
                if not pt:
                    continue

                if name_param:
                    full_name = f"{pt.salutation or ''} {pt.firstName or ''} {pt.lastName or ''}".lower()
                    if name_param.lower() not in full_name and name_param.lower() not in (pt.mobilePhone or ''):
                        continue

                room_no = None
                bed_no = None
                if adm.roomShitingDetails:
                    active_shift_rooms = [r for r in adm.roomShitingDetails if r.get("is_roomActive") is True]
                    if active_shift_rooms:
                        room_no = active_shift_rooms[-1].get("newRoomNo")
                        bed_no = active_shift_rooms[-1].get("newBedNo")

                if room_no is None and adm.room_details:
                    active_rooms = [r for r in adm.room_details if r.get("is_roomActive") is True]
                    latest_room = active_rooms[-1] if active_rooms else adm.room_details[-1]
                    room_no = latest_room.get("roomNo")
                    bed_no = latest_room.get("bedNo")

                comp_code = (adm.company_code or getattr(pt, 'company_code', '') or '').strip()
                comp_name = insurance_map.get(comp_code, None) if comp_code else None
                if not comp_name and getattr(adm, 'insurance_company', None):
                    comp_name = adm.insurance_company

                results_list.append({
                    'ipNumber': adm.ipNumber,
                    'ip_number': adm.ipNumber,
                    'uhid': adm.uhid,
                    'salutation': getattr(pt, 'salutation', ''),
                    'firstName': pt.firstName,
                    'lastName': pt.lastName,
                    'age': adm.age or pt.age,
                    'age_type': adm.age_type or pt.age_type,
                    'gender': pt.gender,
                    'dob': pt.dob,
                    'mobilePhone': pt.mobilePhone,
                    'area': pt.area,
                    'city': pt.city,
                    'state': pt.state,
                    'zipcode': pt.zipcode,
                    'customer_type': adm.customer_type or getattr(pt, 'customer_type', ''),
                    'company_code': comp_code,
                    'company_name': comp_name,
                    'room_no': room_no,
                    'bed_no': bed_no,
                    'admittingDoctor': getattr(adm, 'admittingDoctor', '') or '',
                    'consultingDoctor': getattr(adm, 'consultingDoctor', '') or '',
                    'doctorName': getattr(adm, 'admittingDoctor', '') or getattr(adm, 'consultingDoctor', '') or getattr(pt, 'doctorName', '') or '',
                    'doctor': getattr(adm, 'admittingDoctor', '') or getattr(adm, 'consultingDoctor', '') or getattr(pt, 'doctorName', '') or '',
                    'is_admitted': getattr(adm, 'is_admitted', False),
                    'is_discharged': adm.is_discharged,
                    'admitted': getattr(adm, 'is_admitted', False) and not adm.is_discharged,
                    'is_high_risk': bool(getattr(adm, 'is_high_risk', False)),
                    'high_risk_reason': getattr(adm, 'high_risk_reason', '') or '',
                    'high_risk_date': getattr(adm, 'high_risk_date', None).isoformat() if hasattr(getattr(adm, 'high_risk_date', None), 'isoformat') else (str(getattr(adm, 'high_risk_date', '')) if getattr(adm, 'high_risk_date', None) else None),
                })

            return Response({
                "success": True,
                "data": results_list,
                "results": results_list
            }, status=200)

        # Single direct lookup
        admission_query = {"ipNumber": ipNumber}
        if hospital_code and hospital_code != "system":
            admission_query["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            admission_query["branch_code"] = branch_code

        admission = Admission.objects.filter(**admission_query).first()
        if not admission:
            ip_clean = str(ipNumber).strip()
            fallback_q = _build_ip_search_query(ip_clean)
            if hospital_code and hospital_code != "system":
                fallback_q &= Q(hospital_code=hospital_code)
            if branch_code and branch_code != "system":
                fallback_q &= Q(branch_code=branch_code)
            admission = Admission.objects.filter(fallback_q).order_by('-ipNumber').first()

        if not admission:
            return Response(
                {"error": "Admission record not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        patient_query = {"uhid": admission.uhid}
        if hospital_code and hospital_code != "system":
            patient_query["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            patient_query["branch_code"] = branch_code

        patient = Patient.objects.filter(**patient_query).first()
        if not patient:
            return Response(
                {"error": "Patient not found for the given UHID"},
                status=status.HTTP_404_NOT_FOUND
            )

        company_code = (getattr(admission, 'company_code', None) or getattr(patient, 'company_code', None) or "").strip()
        company_name = None
        if company_code:
            insurance = InsuranceProvider.objects.filter(
                company_code=company_code
            ).first()
            if insurance:
                company_name = insurance.company_name
        if not company_name and getattr(admission, 'insurance_company', None):
            company_name = admission.insurance_company

        room_no = None
        bed_no = None
        if admission.roomShitingDetails:
            active_shift_rooms = [
                r for r in admission.roomShitingDetails
                if r.get("is_roomActive") is True
            ]
            if active_shift_rooms:
                latest_shift = active_shift_rooms[-1]
                room_no = latest_shift.get("newRoomNo")
                bed_no = latest_shift.get("newBedNo")

        if room_no is None and admission.room_details:
            active_rooms = [
                r for r in admission.room_details
                if r.get("is_roomActive") is True
            ]
            latest_room = active_rooms[-1] if active_rooms else admission.room_details[-1]
            room_no = latest_room.get("roomNo")
            bed_no = latest_room.get("bedNo")

        from datetime import timezone as py_timezone, timedelta as py_timedelta
        IST = py_timezone(py_timedelta(hours=5, minutes=30))

        adm_date = None
        adm_time = None
        if admission.admissionDateTime:
            dt = admission.admissionDateTime
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=py_timezone.utc)
                dt_ist = dt.astimezone(IST)
                adm_date = dt_ist.strftime("%Y-%m-%d")
                adm_time = dt_ist.strftime("%H:%M")

        response_data = {
            'ipNumber': admission.ipNumber,
            'ipserial_number': admission.ipserial_number,
            'uhid': admission.uhid,
            'roomNo': room_no,
            'bedNo': bed_no,
            'room_details': admission.room_details,
            'roomShitingDetails': getattr(admission, 'roomShitingDetails', []),
            'admissionDate': adm_date,
            'admissionTime': adm_time,
            'admittingDoctor': admission.admittingDoctor,
            'consultingDoctor': admission.consultingDoctor,
            'packageName': admission.packageName,
            'reasonForAdmission': admission.reasonForAdmission,
            'is_discharged': admission.is_discharged,
            'is_admitted': getattr(admission, 'is_admitted', False),
            'is_high_risk': bool(getattr(admission, 'is_high_risk', False)),
            'high_risk_reason': getattr(admission, 'high_risk_reason', '') or '',
            'high_risk_date': getattr(admission, 'high_risk_date', None).isoformat() if hasattr(getattr(admission, 'high_risk_date', None), 'isoformat') else (str(getattr(admission, 'high_risk_date', '')) if getattr(admission, 'high_risk_date', None) else None),
            'salutation': getattr(patient, 'salutation', ''),
            'firstName': patient.firstName,
            'lastName': patient.lastName,
            'age': admission.age,
            'age_type': admission.age_type,
            'gender': patient.gender,
            'dob': patient.dob,
            'mobilePhone': patient.mobilePhone,
            'area': patient.area,
            'city': patient.city,
            'state': patient.state,
            'zipcode': patient.zipcode,
            'customer_type': admission.customer_type or patient.customer_type,
            'company_code': company_code,
            'company_name': company_name,
        }

        return Response(response_data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response(
            {"error": f"An error occurred: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )       
 
@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def estimate_billing_create(request):
    if request.method == 'POST':
        current_user = request.data.get('auth-user-id', 'system')
        branch_code = request.data.get('auth-branch-code', 'system')
        outlet_code = request.data.get('auth-outlet-code', 'system')
        hospital_code = request.data.get('auth-hospital-code', 'system')

        with transaction.atomic():
            last_bill = EstimateBilling.objects.select_for_update().order_by('-id').first()

            if last_bill and last_bill.EstBillNo:
                last_number = int(last_bill.EstBillNo)
                next_number = last_number + 1
            else:
                next_number = 1

            formatted_bill_no = f"{next_number:06d}"

            while EstimateBilling.objects.filter(EstBillNo=formatted_bill_no).exists():
                next_number += 1
                formatted_bill_no = f"{next_number:06d}"

            request_data = {k: v for k, v in request.data.items()
                            if not k.startswith('auth-')}

            request_data['EstBillNo'] = formatted_bill_no
            request_data['EstBillDate'] = timezone.now()   # ← server time
            request_data['created_by'] = current_user      # ← from auth header
            request_data['branch_code'] = branch_code      # ← from auth header
            request_data['hospital_code'] = hospital_code      # ← from auth header
            request_data['outlet_code'] = outlet_code      # ← from auth header

            serializer = EstimateBillingSerializer(data=request_data)
            if serializer.is_valid():
                serializer.save()
                return Response({'message': 'Form data saved successfully!', 'EstBillNo': formatted_bill_no}, status=201)

            return Response(serializer.errors, status=400)

def serialize_val(val):
    """Make a single value JSON-safe."""
    if isinstance(val, Decimal128):
        return float(val.to_decimal())
    if isinstance(val, ObjectId):
        return str(val)
    if isinstance(val, datetime):
        return val.isoformat()
    return val


def serialize_doc(doc):
    """Recursively convert Mongo document to JSON-safe dict."""
    if isinstance(doc, dict):
        return {k: serialize_doc(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [serialize_doc(i) for i in doc]
    return serialize_val(doc)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def estimate_billing_list(request):
    try:
        branch_code   = request.data.get('auth-branch-code')
        outlet_code   = request.data.get('auth-outlet-code')
        hospital_code = request.data.get('auth-hospital-code')

        from_date_str   = (request.GET.get('fromDate') or request.GET.get('start_date') or '').strip()
        to_date_str     = (request.GET.get('toDate') or request.GET.get('end_date') or '').strip()
        bill_type_param = request.GET.get('billType',     '').strip()
        doctor_param    = request.GET.get('doctor',       '').strip()
        uhid_param      = request.GET.get('uhid',         '').strip()
        patient_type    = request.GET.get('patientType',  '').strip()

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        global_db = client['Global']

        estimate_collection      = db['hospital_estimatebilling']
        patient_collection       = db['hospital_patient']
        billtype_collection      = db['hospital_billtype']
        diagnostics_profile_coll = global_db['backend_diagnostics_profile']   # ← new

        # ── Base Query ───────────────────────────────────────────────────────
        query = {"is_active": {"$nin": [False, 0, "false", "False"]}}

        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code
        if outlet_code:
            query["outlet_code"] = outlet_code

        print("ESTIMATE QUERY:", query)

        # ── Date filter (IST-aware) ──────────────────────────────────────────
        date_q = {}
        if from_date_str:
            try:
                date_q["$gte"] = _parse_ist_date_bound(from_date_str, is_end=False)
            except ValueError:
                client.close()
                return Response(
                    {"error": "Invalid fromDate format. Use YYYY-MM-DD."},
                    status=400,
                )
        if to_date_str:
            try:
                date_q["$lte"] = _parse_ist_date_bound(to_date_str, is_end=True)
            except ValueError:
                client.close()
                return Response(
                    {"error": "Invalid toDate format. Use YYYY-MM-DD."},
                    status=400,
                )
        if date_q:
            query["EstBillDate"] = date_q

        # ── Bill type filter ─────────────────────────────────────────────────
        if bill_type_param:
            try:
                int_val = int(bill_type_param)
                query["bill_type"] = {"$in": [int_val, str(int_val)]}
            except (ValueError, TypeError):
                query["bill_type"] = {"$in": [bill_type_param]}

        # ── Doctor filter ────────────────────────────────────────────────────
        if doctor_param:
            query["doctor"] = doctor_param

        # ── UHID filter ──────────────────────────────────────────────────────
        if uhid_param:
            query["uhid"] = {"$regex": uhid_param, "$options": "i"}

        # ── Patient type filter ──────────────────────────────────────────────
        if patient_type == "IP":
            query["ipNumber"] = {"$exists": True, "$ne": "", "$nin": [None]}
        elif patient_type == "OP":
            query["$or"] = [
                {"ipNumber": {"$exists": False}},
                {"ipNumber": ""},
                {"ipNumber": None},
            ]

        # ── Fetch data ───────────────────────────────────────────────────────
        data = list(estimate_collection.find(query).sort("_id", -1))

        # ── Patient Cache ────────────────────────────────────────────────────
        uhids = {doc.get("uhid") for doc in data if doc.get("uhid")}
        patient_cache = {}

        if uhids:
            patient_query = {"uhid": {"$in": list(uhids)}}
            if hospital_code:
                patient_query["hospital_code"] = hospital_code
            if branch_code:
                patient_query["branch_code"] = branch_code

            patients = patient_collection.find(
                patient_query,
                {
                    "_id": 0, "uhid": 1, "salutation": 1,
                    "firstName": 1, "lastName": 1, "age": 1, "gender": 1
                }
            )
            for p in patients:
                patient_cache[p["uhid"]] = p

        # ── Bill Type Cache ──────────────────────────────────────────────────
        bill_type_ids = set()
        for doc in data:
            bt = doc.get("bill_type")
            if bt:
                try:
                    bill_type_ids.add(int(bt))
                except:
                    pass

        bill_type_cache = {}
        if bill_type_ids:
            bt_query = {"bill_type": {"$in": list(bill_type_ids)}}
            if hospital_code:
                bt_query["hospital_code"] = hospital_code
            if branch_code:
                bt_query["branch_code"] = branch_code
            if outlet_code:
                bt_query["outlet_code"] = outlet_code

            bt_docs = billtype_collection.find(
                bt_query,
                {"_id": 0, "bill_type": 1, "bill_name": 1, "billTypeNo": 1}
            )
            for bt in bt_docs:
                bill_type_cache[int(bt["bill_type"])] = {
                    "bill_name":  bt.get("bill_name",  ""),
                    "billTypeNo": bt.get("billTypeNo", "")
                }

        # ── Doctor / ReferredBy Cache ────────────────────────────────────────
        doctor_ids      = set()
        referred_by_ids = set()

        for doc in data:
            doc_val = doc.get("doctor", "")
            ref_val = doc.get("referredBy", "")

            if doc_val and str(doc_val).upper() != "SELF":
                doctor_ids.add(str(doc_val))
            if ref_val and str(ref_val).upper() != "SELF":
                referred_by_ids.add(str(ref_val))

        diagnostics_profile_cache = {}   # employeeId → employeeName

        all_profile_ids = doctor_ids | referred_by_ids
        if all_profile_ids:
            profile_docs = diagnostics_profile_coll.find(
                {"employeeId": {"$in": list(all_profile_ids)}},
                {"_id": 0, "employeeId": 1, "employeeName": 1}
            )
            for p in profile_docs:
                emp_id = str(p.get("employeeId", ""))
                if emp_id:
                    diagnostics_profile_cache[emp_id] = p.get("employeeName", "")

        # ── Enrich Data ──────────────────────────────────────────────────────
        result = []

        for doc in data:
            uhid = doc.get("uhid", "").strip()
            
            if uhid:
                patient = patient_cache.get(uhid, {})
                doc["salutation"] = patient.get("salutation", "")
                doc["firstName"]  = patient.get("firstName",  "")
                doc["lastName"]   = patient.get("lastName",   "")
                doc["gender"]     = patient.get("gender",     "")
            else:
                # Manual entry — fields already stored directly on the estimate doc
                doc["salutation"] = doc.get("salutation", "")
                doc["firstName"]  = doc.get("firstName",  "")
                doc["lastName"]   = doc.get("lastName",   "")
                doc["gender"]     = doc.get("gender",     "")

            # Age / room — always from the estimate doc
            doc["age"]      = doc.get("age",      "")
            doc["age_type"] = doc.get("age_type", "")
            doc["roomNo"]   = doc.get("roomNo",   "")

            try:
                bt_key = int(doc.get("bill_type", 0))
            except:
                bt_key = 0

            bt_info = bill_type_cache.get(bt_key, {})
            doc["bill_name"]  = bt_info.get("bill_name",  "")
            doc["billTypeNo"] = bt_info.get("billTypeNo", "")

            # ── Doctor name ──────────────────────────────────────────────────
            doc_val = doc.get("doctor", "")
            if doc_val and str(doc_val).upper() == "SELF":
                doc["doctorName"] = "SELF"
            else:
                doc["doctorName"] = diagnostics_profile_cache.get(str(doc_val), "")

            # ── ReferredBy name ──────────────────────────────────────────────
            ref_val = doc.get("referredBy", "")
            if ref_val and str(ref_val).upper() == "SELF":
                doc["referredByName"] = "SELF"
            else:
                doc["referredByName"] = diagnostics_profile_cache.get(str(ref_val), "")

            if isinstance(doc.get("item"), str):
                try:
                    doc["item"] = json.loads(doc["item"])
                except:
                    doc["item"] = []

            result.append(serialize_doc(doc))

        client.close()
        return Response(result)

    except Exception as e:
        return Response(
            {"error": "Failed to fetch estimate billing list", "details": str(e)},
            status=500,
        )

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_bill_types(request):
    try:
        branch_code = request.data.get('auth-branch-code')
        outlet_code = request.data.get('auth-outlet-code')
        hospital_code = request.data.get('auth-hospital-code')

        ignore_outlet = request.GET.get('ignore_outlet') == 'true'

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_billtype']

        query = {"is_active": True}

        if hospital_code:
            query["hospital_code"] = hospital_code

        if branch_code:
            query["branch_code"] = branch_code

        # ✅ FIX: include empty outlet also
        if outlet_code and not ignore_outlet:
            query["$or"] = [
                {"outlet_code": outlet_code},
                {"outlet_code": ""},
                {"outlet_code": {"$exists": False}}
            ]

        print("QUERY:", query)

        bill_types = list(collection.find(
            query,
            {
                "_id": 0,
                "bill_type": 1,
                "bill_name": 1,
                "billTypeNo": 1,
                "outlet_code": 1,
                "is_allowDiscount": 1,
                "ward_medicine": 1,
                "ward_lab": 1,
                "ward_radiology": 1,
                "ward_request": 1,
            }
        ))

        client.close()

        return JsonResponse({"billTypes": bill_types}, safe=False)

    except Exception as e:
        return JsonResponse({
            "error": str(e)
        }, status=500)

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_invest_bill_types(request):
    try:
        branch_code = request.data.get('auth-branch-code')
        outlet_code = request.data.get('auth-outlet-code')
        hospital_code = request.data.get('auth-hospital-code')

        ignore_outlet = request.GET.get('ignore_outlet') == 'true'

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_billtype']

        excluded_bill_types = ["AD01", "DIS01", "REG01", "PH01", "SUR01", "CONS01"]
        query = {
            "is_active": True,
            "billTypeNo": {"$nin": excluded_bill_types + [code.lower() for code in excluded_bill_types]}
        }

        if hospital_code:
            query["hospital_code"] = hospital_code

        if branch_code:
            query["branch_code"] = branch_code

        # ✅ FIX: include empty outlet also
        if outlet_code and not ignore_outlet:
            query["$or"] = [
                {"outlet_code": outlet_code},
                {"outlet_code": ""},
                {"outlet_code": {"$exists": False}}
            ]

        print("QUERY:", query)

        raw_bill_types = list(collection.find(
            query,
            {
                "_id": 0,
                "bill_type": 1,
                "bill_name": 1,
                "billTypeNo": 1,
                "outlet_code": 1,
                "is_allowDiscount": 1,
                "is_edit": 1,
                "ward_medicine": 1,
                "ward_lab": 1,
                "ward_radiology": 1,
                "ward_request": 1,
            }
        ))

        client.close()

        excluded_set = {code.upper() for code in excluded_bill_types}
        bill_types = [
            bt for bt in raw_bill_types
            if str(bt.get("billTypeNo", "")).strip().upper() not in excluded_set
        ]

        return JsonResponse({"billTypes": bill_types}, safe=False)

    except Exception as e:
        return JsonResponse({
            "error": str(e)
        }, status=500)
    
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_packages(request):
    try:
        branch_code = request.data.get('auth-branch-code')
        outlet_code = request.data.get('auth-outlet-code')
        hospital_code = request.data.get('auth-hospital-code')

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_package']

        # ✅ Base query
        query = {"is_active": True}

        # ✅ Apply auth filters dynamically
        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code
        if outlet_code:
            query["outlet_code"] = outlet_code

        print("PACKAGE QUERY:", query)

        packages = list(collection.find(
            query,
            {
                "_id": 0,
                "packageNo": 1,
                "packageName": 1
            }
        ))

        client.close()

        return JsonResponse({
            "success": True,
            "packages": packages
        }, safe=False)

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_package_items(request):
    """Fetch package items based on packageNo"""
    try:
        package_no = request.GET.get('packageNo')
        
        if not package_no:
            return JsonResponse({
                "error": "packageNo parameter is required"
            }, status=400)
        
        # Convert to int
        try:
            package_no = int(package_no)
        except (ValueError, TypeError):
            return JsonResponse({
                "error": "packageNo must be a valid integer",
                "packageNo": package_no
            }, status=400)
        
        # Connect to MongoDB
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_package']

        # Fetch package by packageNo
        package_data = collection.find_one(
            {"packageNo": package_no, "is_active": True},
            {"_id": 0, "items": 1, "packageName": 1, "totalPrice": 1}
        )
        
        client.close()

        if package_data and "items" in package_data:
            return JsonResponse({
                "items": package_data["items"],
                "packageName": package_data.get("packageName", ""),
                "totalPrice": package_data.get("totalPrice", "0.00")
            }, safe=True)
        else:
            return JsonResponse({"items": [], "packageName": ""}, safe=True)
    
    except Exception as e:
        return JsonResponse({
            "error": "An error occurred while fetching package items",
            "details": str(e)
        }, status=500)


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_investigation_items(request):
    """Fetch investigation items based on billTypeNo and bill_type from hospital_investigationprice collection
    Special case: When billTypeNo="LAB01", fetch lab tests from Diagnostics database"""
    try:
        bill_type_no = request.GET.get('billTypeNo')
        bill_type = request.GET.get('billType')
        search_query_name = request.GET.get('itemName')
        
        # Validate billTypeNo
        if bill_type_no is None or bill_type_no == 'undefined' or bill_type_no == 'null':
            return JsonResponse({
                "error": "billTypeNo parameter is required and cannot be undefined",
                "received": bill_type_no
            }, status=400)
        
        # Validate billType
        if bill_type is None or bill_type == 'undefined' or bill_type == 'null':
            return JsonResponse({
                "error": "billType parameter is required and cannot be undefined",
                "received": bill_type
            }, status=400)
        
        # Convert bill_type to int (it should always be numeric)
        try:
            bill_type = int(bill_type)
        except (ValueError, TypeError):
            return JsonResponse({
                "error": "billType must be a valid integer",
                "billType": bill_type
            }, status=400)
        
        # Special case: billTypeNo = "LAB01" or "LAB02" (or any LAB category)
        if str(bill_type_no).upper() in ["LAB01", "LAB02"] or str(bill_type_no).upper().startswith("LAB"):
            client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
            
            # 1. Fetch active lab tests from Diagnostics database -> core_testdetails
            diag_db = client['Diagnostics']
            test_collection = diag_db['core_testdetails']
            
            query = {"is_active": True}
            if search_query_name and str(search_query_name).strip():
                import re
                escaped_item = re.escape(str(search_query_name).strip())
                query["test_name"] = {"$regex": escaped_item, "$options": "i"}

            tests = list(test_collection.find(
                query,
                {
                    "test_id": 1,
                    "test_name": 1,
                    "SH_Rate": 1,
                    "shortcut": 1,
                    "Credit_Rate": 1,
                    "_id": 0
                }
            ))

            # 2. Fetch NABH codes & rates from HMS database -> hospital_lab_nabh_rate
            hms_db = client['HMS']
            nabh_collection = hms_db['hospital_lab_nabh_rate']
            nabh_records = list(nabh_collection.find({}, {"_id": 0, "test_id": 1, "nabh_code": 1, "nabh_rate": 1, "non_nabh_rate": 1, "test_name": 1}))

            client.close()

            # Build lookup dictionary: each individual test_id -> nabh_record
            # test_id in hospital_lab_nabh_rate can be a single int OR a list of ints
            # (multiple tests sharing the same nabh_code/rate).
            nabh_map = {}
            for n_rec in nabh_records:
                tid_field = n_rec.get('test_id')
                if tid_field is None:
                    continue
                # Normalise to list so single-int and array are handled the same way
                tid_list = tid_field if isinstance(tid_field, list) else [tid_field]
                for tid in tid_list:
                    if tid is not None:
                        t_str = str(tid).strip()
                        nabh_map[t_str] = n_rec
                        try:
                            nabh_map[str(int(t_str))] = n_rec
                        except Exception:
                            pass

            btn_upper = str(bill_type_no).upper().strip()
            formatted_items = []
            for test in tests:
                t_id = test.get('test_id', '')
                t_id_str = str(t_id).strip() if t_id is not None else ''

                # Lookup NABH record (supporting both string and integer keys)
                nabh_info = nabh_map.get(t_id_str)
                if not nabh_info and t_id_str:
                    try:
                        nabh_info = nabh_map.get(str(int(t_id_str)))
                    except Exception:
                        nabh_info = None

                nabh_code = str(nabh_info.get('nabh_code', '')).strip() if nabh_info else ""
                nabh_rate = nabh_info.get('nabh_rate') if nabh_info else None
                non_nabh_rate = nabh_info.get('non_nabh_rate') if nabh_info else None

                if btn_upper == "LAB01":
                    # LAB01: No nabh_code, price from SH_Rate
                    nabh_code = ""
                    price = test.get('SH_Rate', '0')

                elif btn_upper == "LAB02":
                    # LAB02: NABH rate & NABH code
                    if not nabh_info:
                        continue
                    if nabh_rate is not None and str(nabh_rate).strip() != "" and str(nabh_rate).strip().lower() != "none":
                        price = str(nabh_rate).strip()
                    else:
                        price = "0"

                elif btn_upper == "LAB03":
                    # LAB03: Non-NABH rate & NABH code
                    if not nabh_info:
                        continue
                    if non_nabh_rate is not None and str(non_nabh_rate).strip() != "" and str(non_nabh_rate).strip().lower() != "none":
                        price = str(non_nabh_rate).strip()
                    else:
                        price = "0"

                else:
                    # Fallback for any other LAB category
                    price = test.get('SH_Rate', '0')

                if price is None or str(price).strip().lower() == 'none' or str(price).strip() == '':
                    price = "0"

                formatted_items.append({
                    "itemName": test.get('test_name', ''),
                    "price": str(price),
                    "rate": str(price),
                    "test_id": t_id,
                    "nabh_code": nabh_code,
                    "nabh_rate": nabh_rate,
                    "non_nabh_rate": non_nabh_rate,
                    "no_nabh_rate": non_nabh_rate,
                    "shortcut": (test.get('shortcut') or "").strip(),
                })

            if search_query_name and str(search_query_name).strip():
                import re
                q_clean = str(search_query_name).strip().lower()
                def test_sort_key(it):
                    t_name = str(it.get("itemName", "")).strip().lower()
                    if t_name.startswith(q_clean):
                        return (0, t_name)
                    if re.search(rf'(?:^|\s){re.escape(q_clean)}', t_name):
                        return (1, t_name)
                    return (2, t_name)
                formatted_items.sort(key=test_sort_key)
            else:
                formatted_items.sort(key=lambda it: str(it.get("itemName", "")).strip().lower())

            return JsonResponse({"items": formatted_items}, safe=True)
        
        # Regular case: Fetch from hospital_investigationprice
        # billTypeNo is kept as string (e.g., "X-RAY01", "CT01")
        # Connect to MongoDB
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_investigationprice']

        # Fetch items for the specific billTypeNo (using string comparison)
        investigation_data = collection.find_one(
            {"billTypeNo": bill_type_no},
            {"_id": 0, "Items": 1, "BillType": 1}
        )
        
        client.close()

        if investigation_data and "Items" in investigation_data:
            items = investigation_data["Items"]
            is_surgery_type = str(bill_type_no).upper().startswith(("SUR", "CAT"))
            formatted_items = []
            for item in items:
                item_name = item.get("itemName", "")
                item_id = item.get("item_id", "")
                val = item.get(str(bill_type))
                price = "0"
                nabh_code = ""

                if is_surgery_type:
                    if isinstance(val, dict):
                        price = str(val.get("price", "0")).strip()
                        nabh_code = str(val.get("nabh_code", "")).strip()
                    elif val is not None:
                        price = str(val).strip()
                    if item_name:
                        formatted_items.append({
                            "itemName": item_name,
                            "item_id": item_id,
                            "price": price if (price and price.lower() != "none") else "0",
                            "rate": price if (price and price.lower() != "none") else "0",
                            "nabh_code": nabh_code,
                           "shortcut": (item.get('shortcut') or "").strip(),
                        })
                else:
                    # Only return items where the specific bill_type rate exists
                    if val is None:
                        continue

                    if isinstance(val, dict):
                        price = str(val.get("price", "")).strip()
                        nabh_code = str(val.get("nabh_code", "")).strip()
                    else:
                        price = str(val).strip()
                        nabh_code = ""

                    if price and price != "0" and price.lower() != "none" and item_name:
                        formatted_items.append({
                            "itemName": item_name,
                            "item_id": item_id,
                            "price": price,
                            "rate": price,
                            "nabh_code": nabh_code,
                            "shortcut": (item.get('shortcut') or "").strip(),
                        })

            if search_query_name and str(search_query_name).strip():
                import re
                q_clean = str(search_query_name).strip().lower()
                # Filter matching query
                formatted_items = [
                    it for it in formatted_items
                    if q_clean in str(it.get("itemName", "")).lower()
                ]
                def test_sort_key_nonlab(it):
                    t_name = str(it.get("itemName", "")).strip().lower()
                    if t_name.startswith(q_clean):
                        return (0, t_name)
                    if re.search(rf'(?:^|\s){re.escape(q_clean)}', t_name):
                        return (1, t_name)
                    return (2, t_name)
                formatted_items.sort(key=test_sort_key_nonlab)
            else:
                formatted_items.sort(key=lambda it: str(it.get("itemName", "")).strip().lower())

            return JsonResponse({"items": formatted_items}, safe=True)

        else:
            return JsonResponse({"items": []}, safe=True)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "error": "An error occurred while fetching investigation items",
            "details": str(e)
        }, status=500)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def invest_billing_create(request):
    mongo_client = None

    try:
        current_user = request.data.get('auth-user-id', "system")
        branch_code = request.data.get('auth-branch-code', 'system')
        outlet_code = request.data.get('auth-outlet-code', 'system')
        hospital_code = request.data.get('auth-hospital-code', 'system')

        data = {k: v for k, v in request.data.items()
                if not k.startswith('auth-')}

        # ── Normalize item field ───────────────────────────────
        def normalize_item(item):
            if isinstance(item, list):
                return item   # ✅ keep as list

            elif isinstance(item, str):
                try:
                    parsed = json.loads(item)

                    # Handle double-string case
                    if isinstance(parsed, str):
                        parsed = json.loads(parsed)

                    return parsed if isinstance(parsed, list) else []

                except (json.JSONDecodeError, TypeError):
                    return []

            return []

        if "item" in data:
            data["item"] = normalize_item(data["item"])

        # ── Server-side validation for Age and Age Type ──
        age_val = str(data.get("age", "")).strip()
        age_type_val = str(data.get("age_type", "") or data.get("ageType", "")).strip()

        if not age_val:
            return Response({"error": "Age is required!"}, status=drf_status.HTTP_400_BAD_REQUEST)
        if not age_type_val:
            return Response({"error": "Age Type is required!"}, status=drf_status.HTTP_400_BAD_REQUEST)

        # ── Connect MongoDB ─────────────────────────────────────
        mongo_client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        mongo_db = mongo_client['HMS']
        invest_collection = mongo_db['hospital_investbilling']
        counters_collection = mongo_db['counters']

        # ── Deactivate related estimate & transfer ward request context ───────
        est_bill_no = data.get("EstBillNo")
        est_doc = None
        if est_bill_no:
            est_doc = mongo_db['hospital_estimatebilling'].find_one({"EstBillNo": est_bill_no})
            mongo_db['hospital_estimatebilling'].update_one(
                {"EstBillNo": est_bill_no, "is_active": True},
                {"$set": {
                    "is_active": False,
                    "lastmodified_by": current_user,
                    "lastmodified_date": timezone.now()
                }}
            )

        data.pop("EstBillDate", None)

        # Retain reference to original EstBillNo
        if est_bill_no:
            data["fromEstBillNo"] = est_bill_no
            data["EstBillNo"] = est_bill_no

        if est_doc:
            if est_doc.get("is_ward_request") or data.get("is_ward_request"):
                data["is_ward_request"] = True
                data["ward_request_type"] = est_doc.get("ward_request_type") or data.get("ward_request_type") or "LAB"
            if not data.get("roomNo") and est_doc.get("roomNo"):
                data["roomNo"] = est_doc.get("roomNo")
            if not data.get("wardName") and est_doc.get("wardName"):
                data["wardName"] = est_doc.get("wardName")
            if not data.get("ipNumber") and est_doc.get("ipNumber"):
                data["ipNumber"] = est_doc.get("ipNumber")
            if not data.get("status") and est_doc.get("status"):
                data["status"] = est_doc.get("status")

        bill_type = data.get("bill_type")
        if not bill_type:
            return Response(
                {"error": "bill_type is required"},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        data["investBillDate"] = timezone.now()

       # ───────────────── UPDATE ──────────────────────────────
        existing_invest_bill_no = data.get("investBillNo")
        if existing_invest_bill_no:

            existing_record = invest_collection.find_one(
                {"investBillNo": existing_invest_bill_no, "is_active": True}
            )

            if not existing_record:
                return Response(
                    {"error": f"No record found with investBillNo: {existing_invest_bill_no}"},
                    status=drf_status.HTTP_404_NOT_FOUND
                )
            if existing_record.get("is_delete_requested"):
                return Response(
                    {"error": "Delete is pending approval for this bill."},
                    status=drf_status.HTTP_400_BAD_REQUEST
                )

            # ── editRemarks is required for every edit ────────────────────────
            edit_remarks = data.get("editRemarks", "").strip()
            if not edit_remarks:
                return Response(
                    {"error": "editRemarks is required when editing a bill."},
                    status=drf_status.HTTP_400_BAD_REQUEST
                )
            # ── Check payment method: Cash requires approval, Credit does not ──
            pm = str(data.get("paymentMethod") or existing_record.get("paymentMethod") or "").strip().lower()
            is_cash = (pm == "cash")

            # ── Build history snapshot with old & new values of changed fields ─────
            fields_to_ignore = {"_id", "history", "investBillNo", "lastmodified_by",
                                "lastmodified_date", "editRemarks", "created_by",
                                "created_date", "branch_code", "outlet_code", "hospital_code"}

            changed_fields = {}
            for key, new_value in data.items():
                if key in fields_to_ignore:
                    continue
                old_value = existing_record.get(key)
                if old_value != new_value:
                    changed_fields[key] = {
                        "old": old_value,
                        "new": new_value
                    }

            history_edit = {
                "action": "edit",
                "modified_date": timezone.now(),
                "modified_by": current_user,
                "editRemarks": edit_remarks,
                "changes": changed_fields,
                "is_approved": not is_cash,
                "paymentMethod": data.get("paymentMethod") or existing_record.get("paymentMethod") or "",
            }

            data["lastmodified_by"] = current_user
            data["lastmodified_date"] = timezone.now()
            data["editRemarks"] = edit_remarks
            if is_cash:
                data["is_approved"] = False
                data["approved_by"] = None
                data["approved_date"] = None
            else:
                data["is_approved"] = True
                data["approved_by"] = current_user
                data["approved_date"] = timezone.now()
            data.pop("investBillNo", None)

            invest_collection.update_one(
                {"_id": existing_record["_id"]},
                {
                    "$set": data,
                    "$push": {"history": history_edit}
                }
            )

            return Response(
                {"message": "Billing updated successfully!",
                "investBillNo": existing_invest_bill_no},
                status=drf_status.HTTP_200_OK
            )
        # ───────────────── CREATE ──────────────────────────────

        # Financial Year Logic
        today = datetime.today()
        if today.month < 4:
            financial_year = f"{(today.year - 1) % 100:02d}{today.year % 100:02d}"
        else:
            financial_year = f"{today.year % 100:02d}{(today.year + 1) % 100:02d}"

        prefix_key = f"{financial_year}{bill_type}"
        prefix = f"{prefix_key}"

        # 🔥 ATOMIC COUNTER (Concurrency Safe)
        counter = counters_collection.find_one_and_update(
            {"_id": prefix_key},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )

        next_number = counter["seq"]
        invest_bill_no = f"{prefix}{next_number:06d}"

        # Stamp fields
        data["investBillNo"] = invest_bill_no
        data["created_by"] = current_user
        data["branch_code"] = branch_code
        data["outlet_code"] = outlet_code
        data["hospital_code"] = hospital_code
        data["created_date"] = timezone.now()
        data["lastmodified_by"] = None
        data["lastmodified_date"] = timezone.now()
        data["is_active"] = True

        # Insert
        invest_collection.insert_one(data)

        if est_bill_no:
            mongo_db['hospital_estimatebilling'].update_one(
                {"EstBillNo": est_bill_no},
                {"$set": {
                    "converted_to_invest_bill": invest_bill_no,
                    "billing_status": "Billed"
                }}
            )

        return Response(
            {"message": "Billing saved successfully!",
             "investBillNo": invest_bill_no},
            status=drf_status.HTTP_201_CREATED
        )

    except Exception as e:
        traceback.print_exc()
        return Response(
            {"error": "Billing failed", "details": repr(e)},
            status=500
        )

    finally:
        if mongo_client:
            mongo_client.close()



@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def billing_report_view(request):

    def serialize_doc(doc):
        if isinstance(doc, dict):
            return {k: serialize_doc(v) for k, v in doc.items()}
        elif isinstance(doc, list):
            return [serialize_doc(i) for i in doc]
        elif isinstance(doc, Decimal128):
            return float(doc.to_decimal())
        elif isinstance(doc, ObjectId):
            return str(doc)
        elif isinstance(doc, datetime):
            return doc.isoformat()
        return doc

    try:
        branch_code   = request.data.get('auth-branch-code',   'system')
        outlet_code   = request.data.get('auth-outlet-code',   'system')
        hospital_code = request.data.get('auth-hospital-code', 'system')

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        global_db = client['Global']

        collection               = db['hospital_investbilling']
        bill_type_collection     = db['hospital_billtype']
        patient_collection       = db['hospital_patient']
        refund_collection        = db['hospital_investrefund']
        diagnostics_profile_coll = global_db['backend_diagnostics_profile']  # ← new

        # ── Base Query ─────────────────────────────────────────
        query = {}
        is_active_param = request.GET.get('is_active')
        if is_active_param is not None:
            if str(is_active_param).lower() in ['true', '1']:
                query["is_active"] = True
            elif str(is_active_param).lower() in ['false', '0']:
                query["is_active"] = False

        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code
        if outlet_code:
            query["outlet_code"] = outlet_code

        print("BILLING QUERY:", query)

        # ── Date filter (IST-aware) ────────────────────────────
        start_date = (request.GET.get('start_date') or request.GET.get('fromDate') or '').strip()
        end_date   = (request.GET.get('end_date') or request.GET.get('toDate') or '').strip()

        date_q = {}
        if start_date:
            try:
                date_q["$gte"] = _parse_ist_date_bound(start_date, is_end=False)
            except ValueError:
                return JsonResponse({"error": "Invalid start_date format. Use YYYY-MM-DD."}, status=400)
        if end_date:
            try:
                date_q["$lte"] = _parse_ist_date_bound(end_date, is_end=True)
            except ValueError:
                return JsonResponse({"error": "Invalid end_date format. Use YYYY-MM-DD."}, status=400)
        if date_q:
            query["investBillDate"] = date_q

        # ── Bill type filter ───────────────────────────────────
        bill_type_param = request.GET.get('billType')
        if bill_type_param:
            try:
                query["bill_type"] = int(bill_type_param)
            except:
                query["bill_type"] = bill_type_param

        bill_type_no_param = request.GET.get('billTypeNo')
        if bill_type_no_param:
            btypes = [b.strip() for b in bill_type_no_param.split(",") if b.strip()]
            if len(btypes) == 1:
                query["billTypeNo"] = btypes[0]
            elif len(btypes) > 1:
                query["billTypeNo"] = {"$in": btypes}

        # ── Doctor filter ──────────────────────────────────────
        doctor_param = request.GET.get('doctor')
        if doctor_param:
            query["doctor"] = doctor_param

        # ── UHID filter ────────────────────────────────────────
        uhid_param = request.GET.get('uhid')
        if uhid_param:
            query["uhid"] = {"$regex": uhid_param, "$options": "i"}

        # ── IP Number filter ───────────────────────────────────
        ip_param = request.GET.get('ipNumber')
        if ip_param:
            query["ipNumber"] = {"$regex": f"^{re.escape(ip_param.strip())}$", "$options": "i"}

        # ── Patient type filter ────────────────────────────────
        patient_type_param = request.GET.get('patientType')
        if patient_type_param == 'IP':
            query["ipNumber"] = {"$exists": True, "$ne": "", "$nin": [None]}
        elif patient_type_param == 'OP':
            query["$or"] = [
                {"ipNumber": {"$exists": False}},
                {"ipNumber": ""},
                {"ipNumber": None},
            ]

        # ── Fetch billing data ─────────────────────────────────
        data = list(collection.find(query))

        # ── Batch Refund Cache ─────────────────────────────────
        invest_bill_nos = [
            doc.get("investBillNo") for doc in data if doc.get("investBillNo")
        ]

        refunded_test_ids = {}
        refund_details = {}

        if invest_bill_nos:
            refund_docs = refund_collection.find(
                {
                    "investBillNo": {"$in": invest_bill_nos},
                    "is_active": True
                },
                {"_id": 0, "investBillNo": 1, "item": 1,
         "refundBillNo": 1, "refundBillDate": 1, "refundRemarks": 1,
         "is_approved": 1, "approved_by": 1, "approved_date": 1}
            )

            for rdoc in refund_docs:
                bill_no = rdoc.get("investBillNo")
                items   = rdoc.get("item", [])

                if isinstance(items, str):
                    try:
                        items = json.loads(items)
                    except:
                        items = []

                if bill_no not in refunded_test_ids:
                    refunded_test_ids[bill_no] = set()

                for it in items:
                    tid = it.get("item_id") or it.get("test_id")
                    if tid is not None:
                        try:
                            refunded_test_ids[bill_no].add(int(tid))
                        except (ValueError, TypeError):
                            refunded_test_ids[bill_no].add(tid)

                            # ← NEW: collect full refund doc per bill
                    if bill_no not in refund_details:
                        refund_details[bill_no] = []
                    refund_details[bill_no].append({
                        "refundBillNo":   rdoc.get("refundBillNo", ""),
                        "refundBillDate": rdoc.get("refundBillDate", ""),
                        "refundRemarks":  rdoc.get("refundRemarks", ""),
                        "is_approved":    rdoc.get("is_approved", False),
                        "approved_by":    rdoc.get("approved_by", None),
                        "approved_date":  rdoc.get("approved_date", None),
                        "item":           items,
                    })

        # ── Batch Patient Cache ────────────────────────────────
        uhids = {doc.get("uhid") for doc in data if doc.get("uhid")}
        patient_cache = {}

        if uhids:
            patient_query = {"uhid": {"$in": list(uhids)}}
            if hospital_code:
                patient_query["hospital_code"] = hospital_code
            if branch_code:
                patient_query["branch_code"] = branch_code

            patients = patient_collection.find(
                patient_query,
                {
                    "_id": 0, "uhid": 1, "salutation": 1,
                    "firstName": 1, "lastName": 1, "age": 1, "gender": 1
                }
            )
            for p in patients:
                patient_cache[p["uhid"]] = p

        # ── Batch Bill Type Cache ──────────────────────────────
        bill_type_ids = set()
        for doc in data:
            bt = doc.get("bill_type")
            if bt:
                try:
                    bill_type_ids.add(int(bt))
                except:
                    pass

        bill_type_cache = {}
        if bill_type_ids:
            bt_docs = bill_type_collection.find(
                {"bill_type": {"$in": list(bill_type_ids)}},
                {"_id": 0, "bill_type": 1, "bill_name": 1, "billTypeNo": 1}
            )
            for bt in bt_docs:
                bill_type_cache[int(bt["bill_type"])] = {
                    "bill_name":  bt.get("bill_name",  ""),
                    "billTypeNo": bt.get("billTypeNo", "")
                }

        # ── Batch Doctor / ReferredBy / Approver Cache ────────────────────
        # Collect all employee IDs that are NOT "SELF"
        doctor_ids      = set()
        referred_by_ids = set()
        approved_by_ids = set()

        for doc in data:
            doc_val = doc.get("doctor", "")
            ref_val = doc.get("referredBy", "")
            app_val = doc.get("approved_by")

            if doc_val and doc_val.upper() != "SELF":
                doctor_ids.add(str(doc_val))

            if ref_val and ref_val.upper() != "SELF":
                referred_by_ids.add(str(ref_val))

            if app_val:
                approved_by_ids.add(str(app_val).strip())

        # One query covers all sets — union of all IDs needed
        all_profile_ids = doctor_ids | referred_by_ids | approved_by_ids
        diagnostics_profile_cache = {}   # employeeId → full name string

        if all_profile_ids:
            profile_docs = diagnostics_profile_coll.find(
                {"employeeId": {"$in": list(all_profile_ids)}},
                {"_id": 0, "employeeId": 1, "employeeName": 1}
            )
            for p in profile_docs:
                emp_id   = str(p.get("employeeId", ""))
                emp_name = p.get("employeeName", "")
                if emp_id:
                    diagnostics_profile_cache[emp_id] = emp_name

        # ── Enrich & Filter Data ───────────────────────────────
        result = []

        for doc in data:

            # Patient — use patient_cache if uhid exists, else fall back to doc fields
            uhid = doc.get("uhid", "").strip()
            if uhid:
                patient = patient_cache.get(uhid, {})
                doc["salutation"] = patient.get("salutation", "")
                doc["firstName"]  = patient.get("firstName",  "")
                doc["lastName"]   = patient.get("lastName",   "")
                doc["gender"]     = patient.get("gender",     "")
            else:
                # Manual entry — fields already stored directly on the billing doc
                doc["salutation"] = doc.get("salutation", "")
                doc["firstName"]  = doc.get("firstName",  "")
                doc["lastName"]   = doc.get("lastName",   "")
                doc["gender"]     = doc.get("gender",     "")

            # Age / room — always from the billing doc (not patient_cache)
            doc["age"]      = doc.get("age",    "")
            doc["age_type"] = doc.get("age_type", "")
            doc["roomNo"]   = doc.get("roomNo",   "")

            # Bill type
            try:
                bt_key = int(doc.get("bill_type", 0))
            except:
                bt_key = 0

            bt_info = bill_type_cache.get(bt_key, {})
            doc["bill_name"]  = bt_info.get("bill_name",  "")
            doc["billTypeNo"] = bt_info.get("billTypeNo", "")

            # ── Doctor name ────────────────────────────────────
            doc_val = doc.get("doctor", "")
            if doc_val and doc_val.upper() == "SELF":
                doc["doctorName"] = "SELF"
            else:
                doc["doctorName"] = diagnostics_profile_cache.get(str(doc_val), str(doc_val) if doc_val else "")

            # ── ReferredBy name ────────────────────────────────
            ref_val = doc.get("referredBy", "")
            if ref_val and ref_val.upper() == "SELF":
                doc["referredByName"] = "SELF"
            else:
                doc["referredByName"] = diagnostics_profile_cache.get(str(ref_val), "")

            # Parse items
            items = doc.get("item", [])
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except:
                    items = []

            # ── Exclude already-refunded items ─────────────────
            bill_no          = doc.get("investBillNo", "")
            already_refunded = refunded_test_ids.get(bill_no, set())
            doc["original_items"] = items

            if already_refunded:
                filtered_items = []
                for it in items:
                    tid = it.get("item_id") or it.get("test_id")
                    try:
                        tid_norm = int(tid) if tid is not None else None
                    except (ValueError, TypeError):
                        tid_norm = tid

                    if tid_norm not in already_refunded:
                        filtered_items.append(it)
                doc["item"] = filtered_items

                # Recalculate total, discount, and finalPrice for remaining items
                new_total = sum(float(it.get("price", 0) or 0) * int(it.get("quantity", 1) or 1) for it in filtered_items)
                orig_total = float(doc.get("total", 0) or 0)
                orig_disc = float(doc.get("discount", 0) or 0)
                disc_pct = float(doc.get("discountPercent", 0) or 0)
                orig_final = float(doc.get("finalPrice", 0) or 0)

                doc["original_total"] = orig_total
                doc["original_finalPrice"] = orig_final

                is_package_bill = bool(doc.get("package_id") or doc.get("billTypeNo") == "PACK" or doc.get("billType") == "PACK")
                if is_package_bill or (new_total == 0 and orig_total > 0 and len(filtered_items) > 0):
                    if not filtered_items:
                        doc["total"] = 0.0
                        doc["discount"] = 0.0
                        doc["finalPrice"] = 0.0
                    else:
                        doc["total"] = orig_total
                        doc["discount"] = orig_disc
                        doc["finalPrice"] = orig_final if orig_final > 0 else max(0.0, round(orig_total - orig_disc, 2))
                else:
                    doc["total"] = new_total
                    if disc_pct > 0:
                        new_disc = round((new_total * disc_pct) / 100.0, 2)
                    elif orig_total > 0 and orig_disc > 0:
                        new_disc = round((new_total / orig_total) * orig_disc, 2)
                    else:
                        new_disc = 0.0
                    doc["discount"] = new_disc
                    doc["finalPrice"] = max(0.0, round(new_total - new_disc, 2))
            else:
                doc["item"] = items

            # Check if deleted
            doc["is_delete_requested"] = bool(doc.get("is_delete_requested", False))
            is_deleted = (doc.get("is_active") is False) or (bool(doc.get("is_delete_requested")) and bool(doc.get("is_approved")))
            if is_deleted:
                doc["is_deleted"] = True
                doc["paymentStatus"] = "Deleted"
                doc["is_delete_requested"] = False

            # Check if all items refunded (Sales Returned)
            bill_refunds_check = refund_details.get(bill_no, [])
            if not doc["item"] and (items or bill_refunds_check):
                doc["is_fully_refunded"] = True
                if not is_deleted:
                    doc["paymentStatus"] = "Sales Returned"

            # ← NEW: attach refund details to the bill
            doc["refunds"] = bill_refunds_check

            # Approved By Name
            app_val = str(doc.get("approved_by")or "").strip()
            if app_val:
                doc["approved_by_name"] = diagnostics_profile_cache.get(app_val, app_val)
                doc["approvedByName"] = doc["approved_by_name"]
            else:
                doc["approved_by_name"] = ""
                doc["approvedByName"] = ""

            # Ensure latest editRemarks is populated on doc
            if not doc.get("editRemarks") and isinstance(doc.get("history"), list) and doc["history"]:
                for h in reversed(doc["history"]):
                    if h.get("editRemarks"):
                        doc["editRemarks"] = h["editRemarks"]
                        break

            result.append(serialize_doc(doc))

        client.close()

        result.sort(key=lambda x: x.get("investBillDate", ""), reverse=True)

        return JsonResponse(result, safe=False)

    except Exception as e:
        return JsonResponse(
            {"error": "Failed to generate billing report", "details": str(e)},
            status=500
        )



@api_view(['PATCH'])
@csrf_exempt
@permission_classes([HasRoleAndDataPermission])
def delete_bill_view(request):
    client = None
    try:
        investBillNo   = request.data.get('investBillNo')
        delete_remarks = (request.data.get('deleteRemarks') or '').strip()
        employeeId     = request.data.get('auth-user-id', 'system')

        if not investBillNo:
            return JsonResponse({'error': 'Missing investBillNo'}, status=400)
        if not delete_remarks:
            return JsonResponse({'error': 'deleteRemarks is required'}, status=400)

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        now = timezone.now()

        # Cash requires approval in Dept BUD Report; Credit is directly deleted with audit.
        # Neither stores is_approved: True by default.
        existing_bill = db['hospital_investbilling'].find_one(
            {"$or": [{"investBillNo": investBillNo}, {"EstBillNo": investBillNo}], "is_active": True}
        )
        if not existing_bill:
            existing_bill = db['hospital_estimatebilling'].find_one(
                {"EstBillNo": investBillNo, "is_active": True}
            )

        pm = str((existing_bill.get('paymentMethod') if existing_bill else None) or request.data.get('paymentMethod', '')).strip().lower()
        is_cash = (pm == 'cash')

        if is_cash:
            # Cash bill: requires approval in Dept BUD Report
            update_data = {
                "is_delete_requested": True,
                "deletedBy":           employeeId,
                "deletedAt":           now,
                "deleteRemarks":       delete_remarks,
                "is_approved":         False,
                "approved_by":         None,
                "approved_date":       None,
            }
        else:
            # Credit bill: directly store is_approved: True and is_active: False
            update_data = {
                "is_active":           False,
                "is_delete_requested": True,
                "deletedBy":           employeeId,
                "deletedAt":           now,
                "deleteRemarks":       delete_remarks,
                "is_approved":         True,
                "approved_by":         employeeId,
                "approved_date":       now,
            }

        delete_history_entry = {
            "action": "delete",
            "modified_date": now,
            "modified_by": employeeId,
            "editRemarks": delete_remarks,
            "deleteRemarks": delete_remarks,
            "is_approved": not is_cash,
            "approved_by": employeeId if not is_cash else None,
            "approved_date": now if not is_cash else None,
            "paymentMethod": (existing_bill.get("paymentMethod") if existing_bill else "") or request.data.get('paymentMethod', '') or "",
            "changes": {
                "Status": {
                    "old": "Active",
                    "new": "Deleted" if not is_cash else "Delete Requested",
                },
                "Delete Reason": {
                    "old": "—",
                    "new": delete_remarks,
                },
            }
        }

        result = db['hospital_investbilling'].update_one(
            {
                "$or": [{"investBillNo": investBillNo}, {"EstBillNo": investBillNo}],
                "is_active": True,
                "is_delete_requested": {"$ne": True},
            },
            {
                "$set": update_data,
                "$push": {"history": delete_history_entry}
            }
        )

        if result.matched_count == 0:
            # Estimate bills have no approval flow in the audit report -> keep old behaviour
            result = db['hospital_estimatebilling'].update_one(
                {"EstBillNo": investBillNo, "is_active": True},
                {"$set": {
                    "is_active":     False,
                    "deletedBy":     employeeId,
                    "deletedAt":     now,
                    "deleteRemarks": delete_remarks,
                }}
            )

        if result.matched_count == 0:
            return JsonResponse({'error': 'Bill not found or delete already requested'}, status=404)

        return JsonResponse({'message': 'Delete request submitted for approval'}, status=200)

    except Exception as e:
        return JsonResponse({'error': 'Failed to delete bill', 'details': str(e)}, status=500)
    finally:
        if client:
            client.close()

            
@api_view(['PATCH', 'POST'])
@csrf_exempt
@permission_classes([HasRoleAndDataPermission])
def request_bill_edit_view(request):
    try:
        investBillNo = request.data.get('investBillNo')
        edit_remarks = request.data.get('editRemarks', '').strip()
        employeeId   = request.data.get('auth-user-id', 'system')

        if not investBillNo:
            return JsonResponse({'error': 'Missing investBillNo'}, status=400)

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_investbilling']

        now = timezone.now()
        existing_bill = collection.find_one(
            {"$or": [{"investBillNo": investBillNo}, {"EstBillNo": investBillNo}], "is_active": True}
        )
        if not existing_bill:
            existing_bill = db['hospital_estimatebilling'].find_one(
                {"EstBillNo": investBillNo, "is_active": True}
            )

        pm = str((existing_bill.get('paymentMethod') if existing_bill else None) or request.data.get('paymentMethod', '')).strip().lower()
        is_cash = (pm == 'cash')

        update_fields = {
            "editRemarks":       edit_remarks,
            "lastmodified_by":   employeeId,
            "lastmodified_date": now,
        }
        if is_cash:
            update_fields["is_approved"]   = False
            update_fields["approved_by"]   = None
            update_fields["approved_date"] = None
        else:
            update_fields["is_approved"]   = True
            update_fields["approved_by"]   = employeeId
            update_fields["approved_date"] = now

        result = collection.update_one(
            {"$or": [{"investBillNo": investBillNo}, {"EstBillNo": investBillNo}], "is_active": True},
            {"$set": update_fields}
        )

        if result.matched_count == 0:
            est_col = db['hospital_estimatebilling']
            est_col.update_one(
                {"EstBillNo": investBillNo, "is_active": True},
                {"$set": update_fields}
            )

        client.close()
        return JsonResponse({'message': 'Edit request recorded successfully', 'success': True}, status=200)

    except Exception as e:
        return JsonResponse({'error': 'Failed to record edit request', 'details': str(e)}, status=500)
    
    
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def dept_budr_view(request):

    def serialize_doc(doc):
        if isinstance(doc, dict):
            return {k: serialize_doc(v) for k, v in doc.items()}
        elif isinstance(doc, list):
            return [serialize_doc(i) for i in doc]
        elif isinstance(doc, Decimal128):
            return float(doc.to_decimal())
        elif isinstance(doc, ObjectId):
            return str(doc)
        elif isinstance(doc, datetime):
            return doc.isoformat()
        return doc

    try:
        raw_type = request.GET.get('report_type', '').strip().lower()
        if raw_type in ('delete', 'deleted'):
            report_type = 'deleted'
        elif raw_type in ('edit', 'edited'):
            report_type = 'edited'
        elif raw_type in ('refund', 'refunds'):
            report_type = 'refund'
        else:
            return JsonResponse(
                {"error": "report_type must be 'deleted', 'edited', or 'refund'"},
                status=400,
            )

        start_date = (request.GET.get('start_date') or request.GET.get('fromDate') or '').strip()
        end_date   = (request.GET.get('end_date') or request.GET.get('toDate') or '').strip()
        approval_status = (request.GET.get('approval_status') or '').strip().lower()

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))

        # DBs
        hms_db     = client['HMS']
        global_db  = client['Global']

        invest_collection    = hms_db['hospital_investbilling']
        refund_collection    = hms_db['hospital_investrefund']
        bill_type_collection = hms_db['hospital_billtype']
        outlet_collection    = hms_db['hospital_outlets']

        profile_collection   = global_db['backend_diagnostics_profile']

        # ── Query setup ─────────────────────────────
        if report_type == 'deleted':
            target_collection = invest_collection
            query = {
                    "deletedAt": {"$exists": True},
                    "$or": [
                        {"is_delete_requested": True},   # pending + approved (new flow)
                        {"is_active": False},            # legacy docs deleted before this change
                    ],
                }
            date_field      = "deletedAt"
            actor_id_field  = "deletedBy"
            actor_name_out  = "deletedByName"
        elif report_type == 'edited':
            target_collection = invest_collection
            query = {
            "is_active": True,
            "is_delete_requested": {"$ne": True}, 
                "$or": [
                    {"history": {"$exists": True, "$ne": []}},
                    {"editRemarks": {"$exists": True, "$ne": ""}},
                    {"is_approved": False, "lastmodified_by": {"$ne": None}},
                ]
            }
            date_field      = "lastmodified_date"
            actor_id_field  = "lastmodified_by"
            actor_name_out  = "lastmodified_by_name"
        else:  # 'refund'
            target_collection = refund_collection
            query = {
                "is_active": True,
            }
            date_field      = "refundBillDate"
            actor_id_field  = "created_by"
            actor_name_out  = "created_by_name"

        # ── Approval status filter ──────────────────
        if approval_status == 'approved':
            query["is_approved"] = True
        elif approval_status == 'pending':
            query["is_approved"] = {"$ne": True}

        # ── Date filter (IST-aware) ─────────────────────────
        date_q = {}
        if start_date:
            try:
                date_q["$gte"] = _parse_ist_date_bound(start_date, is_end=False)
            except ValueError:
                client.close()
                return JsonResponse(
                    {"error": "Invalid start_date format. Use YYYY-MM-DD."},
                    status=400,
                )
        if end_date:
            try:
                date_q["$lte"] = _parse_ist_date_bound(end_date, is_end=True)
            except ValueError:
                client.close()
                return JsonResponse(
                    {"error": "Invalid end_date format. Use YYYY-MM-DD."},
                    status=400,
                )
        if date_q:
            query[date_field] = date_q

        data = list(target_collection.find(query))

        # ── Employee mapping (both actors & approvers) ───────────────────────
        user_ids_to_fetch = set()
        for doc in data:
            if doc.get(actor_id_field):
                user_ids_to_fetch.add(str(doc[actor_id_field]).strip())
            if doc.get("approved_by"):
                user_ids_to_fetch.add(str(doc["approved_by"]).strip())
            if doc.get("approvedBy"):
                user_ids_to_fetch.add(str(doc["approvedBy"]).strip())
            if doc.get("created_by"):
                user_ids_to_fetch.add(str(doc["created_by"]).strip())
            if isinstance(doc.get("history"), list):
                for h in doc["history"]:
                    if h.get("modified_by"):
                        user_ids_to_fetch.add(str(h["modified_by"]).strip())

        employee_cache = {}
        if user_ids_to_fetch:
            profiles = profile_collection.find(
                {"employeeId": {"$in": list(user_ids_to_fetch)}},
                {"_id": 0, "employeeId": 1, "employeeName": 1},
            )
            for p in profiles:
                employee_cache[str(p.get("employeeId", "")).strip()] = p.get("employeeName", "")

        # ── Bill type cache ────────────────────────
        bill_type_cache = {}

        # ── Outlet mapping ───────────────────
        outlet_codes = {
            str(doc.get("outlet_code", "")).strip()
            for doc in data
            if doc.get("outlet_code")
        }

        outlet_cache = {}
        if outlet_codes:
            outlets = outlet_collection.find(
                {"outlet_code": {"$in": list(outlet_codes)}},
                {"_id": 0, "outlet_code": 1, "outlet_name": 1}
            )
            for o in outlets:
                outlet_cache[str(o.get("outlet_code", "")).strip()] = o.get("outlet_name", "")

        # ── Patient mapping ───────────────────
        uhids = {
            str(doc.get("uhid", "")).strip()
            for doc in data
            if doc.get("uhid")
        }

        patient_cache = {}
        if uhids:
            try:
                patient_coll = hms_db['hospital_patient']
                patients = patient_coll.find(
                    {"uhid": {"$in": list(uhids)}},
                    {"_id": 0, "uhid": 1, "salutation": 1, "firstName": 1, "middleName": 1, "lastName": 1, "patientName": 1}
                )
                for p in patients:
                    pname = p.get("patientName")
                    if not pname:
                        pname = f"{p.get('salutation', '')} {p.get('firstName', '')} {p.get('middleName', '') or ''} {p.get('lastName', '')}".strip()
                    patient_cache[str(p.get("uhid", "")).strip()] = pname
            except Exception as pe:
                print("Patient lookup error:", pe)

        # ── Enrich refunds with paymentMethod from invest_collection if missing ──
        if report_type == 'refund':
            missing_pm_nos = [doc.get("investBillNo") for doc in data if not doc.get("paymentMethod") and doc.get("investBillNo")]
            if missing_pm_nos:
                try:
                    inv_pm_docs = list(invest_collection.find(
                        {"$or": [{"investBillNo": {"$in": missing_pm_nos}}, {"EstBillNo": {"$in": missing_pm_nos}}]},
                        {"investBillNo": 1, "EstBillNo": 1, "paymentMethod": 1}
                    ))
                    inv_pm_map = {}
                    for idoc in inv_pm_docs:
                        if idoc.get("investBillNo"):
                            inv_pm_map[idoc["investBillNo"]] = idoc.get("paymentMethod", "")
                        if idoc.get("EstBillNo"):
                            inv_pm_map[idoc["EstBillNo"]] = idoc.get("paymentMethod", "")
                    for doc in data:
                        if not doc.get("paymentMethod"):
                            doc["paymentMethod"] = inv_pm_map.get(doc.get("investBillNo"), "")
                except Exception as pme:
                    print("Payment method enrichment error:", pme)

        # ── Process data ───────────────────────────
        result = []

        for doc in data:
            doc["paymentMethod"] = doc.get("paymentMethod") or "—"
            # Bill type
            bill_type = doc.get("bill_type")
            if bill_type:
                if bill_type not in bill_type_cache:
                    try:
                        bt_doc = bill_type_collection.find_one(
                            {"bill_type": int(bill_type)},
                            {"_id": 0, "bill_name": 1, "billTypeNo": 1},
                        )
                        bill_type_cache[bill_type] = {
                            "bill_name":  bt_doc.get("bill_name", "") if bt_doc else "",
                            "billTypeNo": bt_doc.get("billTypeNo", "") if bt_doc else "",
                        }
                    except:
                        bill_type_cache[bill_type] = {"bill_name": "", "billTypeNo": ""}

                doc["bill_name"]  = bill_type_cache[bill_type]["bill_name"]
                doc["billTypeNo"] = bill_type_cache[bill_type]["billTypeNo"]
            else:
                doc["bill_name"]  = ""
                doc["billTypeNo"] = ""

            # Actor name (deletedByName, lastmodified_by_name, created_by_name)
            actor_id = str(doc.get(actor_id_field, "")).strip()
            doc[actor_name_out] = employee_cache.get(actor_id, actor_id or "")

            # Approver name and is_approved status
            approved_by_id = str(doc.get("approved_by") or doc.get("approvedBy") or "").strip()
            app_name = employee_cache.get(approved_by_id, approved_by_id)
            doc["approved_by"] = approved_by_id
            doc["approvedBy"] = approved_by_id
            doc["approved_by_name"] = app_name
            doc["approvedByName"] = app_name

            app_date = doc.get("approved_date") or doc.get("approvedDate")
            doc["approved_date"] = app_date
            doc["approvedDate"] = app_date

            doc["is_approved"] = bool(doc.get("is_approved", False))

            # Patient name
            uhid_str = str(doc.get("uhid", "")).strip()
            if not doc.get("patientName") or doc.get("patientName") == "—":
                doc["patientName"] = patient_cache.get(uhid_str, "—")

            # Outlet name
            outlet_code = str(doc.get("outlet_code", "")).strip()
            doc["outlet_name"] = outlet_cache.get(outlet_code, "")

            # History modified by name
            if isinstance(doc.get("history"), list):
                for h in doc["history"]:
                    mid = str(h.get("modified_by", "")).strip()
                    h["modified_by_name"] = employee_cache.get(mid, mid)

            # Ensure deleted bills always have a deletion event in history
            if report_type == 'deleted':
                hist = list(doc.get("history") or [])
                has_del_entry = any(h.get("action") == "delete" or "deleteRemarks" in h for h in hist)
                if not has_del_entry:
                    del_actor = str(doc.get("deletedBy") or "").strip()
                    del_actor_name = employee_cache.get(del_actor, del_actor)
                    synthetic_del_entry = {
                        "action": "delete",
                        "modified_date": doc.get("deletedAt") or doc.get("lastmodified_date"),
                        "modified_by": del_actor,
                        "modified_by_name": del_actor_name,
                        "editRemarks": doc.get("deleteRemarks") or "",
                        "deleteRemarks": doc.get("deleteRemarks") or "",
                        "is_approved": bool(doc.get("is_approved", False)),
                        "paymentMethod": doc.get("paymentMethod") or "",
                        "changes": {
                            "Status": {
                                "old": "Active",
                                "new": "Deleted" if doc.get("is_active") is False else "Delete Requested",
                            },
                            "Delete Reason": {
                                "old": "—",
                                "new": doc.get("deleteRemarks") or "—",
                            },
                        }
                    }
                    hist.append(synthetic_del_entry)
                doc["history"] = hist

            # Ensure latest editRemarks is populated on doc
            if not doc.get("editRemarks") and isinstance(doc.get("history"), list) and doc["history"]:
                for h in reversed(doc["history"]):
                    if h.get("editRemarks"):
                        doc["editRemarks"] = h["editRemarks"]
                        break

            result.append(serialize_doc(doc))

        client.close()

        result.sort(key=lambda x: x.get(date_field, "") or "", reverse=True)

        return JsonResponse(result, safe=False)

    except Exception as e:
        traceback.print_exc()
        return JsonResponse(
            {"error": "Failed to fetch report", "details": str(e)},
            status=500,
        )


@api_view(['POST', 'PATCH'])
@csrf_exempt
@permission_classes([HasRoleAndDataPermission])
def dept_budr_approve_view(request):
    """
    Approve requested Edit, Delete, or Refund in hospital_investbilling / hospital_investrefund.
    Sets is_approved: True, approved_by: user_id, approved_date: now.
    """
    try:
        user_id     = request.data.get('auth-user-id', 'system')
        action_type = (request.data.get('action_type') or request.data.get('report_type') or '').strip().lower()
        bill_no     = (
            request.data.get('investBillNo') or
            request.data.get('refundBillNo') or
            request.data.get('billNo') or
            ''
        ).strip()
        doc_id      = request.data.get('_id')

        if not action_type or (not bill_no and not doc_id):
            return JsonResponse({'error': 'action_type and bill_no (or _id) are required'}, status=400)

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        global_db = client['Global']
        now = timezone.now()

        if action_type in ('refund', 'refunds'):
            collection = db['hospital_investrefund']
            q = {}
            if doc_id:
                try:
                    q = {"_id": ObjectId(doc_id)}
                except:
                    q = {"refundBillNo": bill_no}
            else:
                q = {"refundBillNo": bill_no}

            res = collection.update_one(
                q,
                {"$set": {
                    "is_approved":       True,
                    "approved_by":       user_id,
                    "approved_date":     now,
                    "lastmodified_by":   user_id,
                    "lastmodified_date": now,
                }}
            )
        elif action_type in ('delete', 'deleted'):
            collection = db['hospital_investbilling']
            if doc_id:
                try:
                    q = {"_id": ObjectId(doc_id)}
                except Exception:
                    q = {"$or": [{"investBillNo": bill_no}, {"EstBillNo": bill_no}]}
            else:
                q = {"$or": [{"investBillNo": bill_no}, {"EstBillNo": bill_no}]}

            q["is_delete_requested"] = True      # only approve real delete requests

            res = collection.update_one(
                q,
                {"$set": {
                    "is_active":     False,      # <-- only here when approved!
                    "is_approved":   True,
                    "approved_by":   user_id,
                    "approved_date": now,
                }}
            )
            # Update history entry to reflect approval
            try:
                collection.update_one(
                    {**q, "history.action": "delete"},
                    {"$set": {
                        "history.$.is_approved": True,
                        "history.$.approved_by": user_id,
                        "history.$.approved_date": now,
                    }}
                )
            except Exception as he:
                print("History approve error:", he)
        elif action_type in ('edit', 'edited'):
            collection = db['hospital_investbilling']
            q = {}
            if doc_id:
                try:
                    q = {"_id": ObjectId(doc_id)}
                except:
                    q = {"$or": [{"investBillNo": bill_no}, {"EstBillNo": bill_no}]}
            else:
                q = {"$or": [{"investBillNo": bill_no}, {"EstBillNo": bill_no}]}

            res = collection.update_one(
                q,
                {"$set": {
                    "is_approved":   True,
                    "approved_by":   user_id,                   
                    "approved_date": now,
                  
                }}
            )
            if res.matched_count == 0:
                est_col = db['hospital_estimatebilling']
                res = est_col.update_one(
                    q,
                    {"$set": {
                        "is_approved":   True,
                        "approved_by":   user_id,                      
                        "approved_date": now,
                       
                    }}
                )
        else:
            client.close()
            return JsonResponse({'error': f'Unsupported action_type: {action_type}'}, status=400)

        # Lookup approver name
        prof = global_db['backend_diagnostics_profile'].find_one(
            {"employeeId": str(user_id).strip()},
            {"_id": 0, "employeeName": 1}
        )
        approved_by_name = prof.get("employeeName", user_id) if prof else user_id

        client.close()

        if res.matched_count == 0:
            return JsonResponse({'error': f'Record not found for {bill_no or doc_id}'}, status=404)

        return JsonResponse({
            'success': True,
            'message': f'{action_type.capitalize()} request approved successfully!',
            'approved_by': user_id,
            'approved_by_name': approved_by_name,
            'approved_date': now.isoformat(),
        }, status=200)

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'error': 'Approval failed', 'details': str(e)}, status=500)
@api_view(['POST'])
@csrf_exempt
@permission_classes([HasRoleAndDataPermission])
def invest_refund_create(request):
    """
    Creates a refund bill for selected items from an existing invest bill.
    refundBillNo is generated by incrementing the last existing refundBillNo
    that matches the same financial-year/bill_type prefix  (no atomic counter).
    """
    mongo_client = None
    try:
        current_user  = request.data.get('auth-user-id',       'system')
        branch_code   = request.data.get('auth-branch-code',   'system')
        outlet_code   = request.data.get('auth-outlet-code',   'system')
        hospital_code = request.data.get('auth-hospital-code', 'system')

        data = {k: v for k, v in request.data.items()
                if not k.startswith('auth-')}

        # ── Validate required fields ────────────────────────────────────────
        required = ['investBillNo', 'uhid', 'bill_type', 'item', 'refund_finalPrice']
        for field in required:
            if not data.get(field):
                return Response(
                    {'error': f'{field} is required'},
                    status=drf_status.HTTP_400_BAD_REQUEST
                )

        # ── Normalize item list ─────────────────────────────────────────────
        item_data = data.get('item', [])
        if isinstance(item_data, str):
            try:
                item_data = json.loads(item_data)
                if isinstance(item_data, str):
                    item_data = json.loads(item_data)
            except (json.JSONDecodeError, TypeError):
                item_data = []
        if not isinstance(item_data, list) or len(item_data) == 0:
            return Response(
                {'error': 'At least one item must be selected for refund'},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        # ── Connect MongoDB ─────────────────────────────────────────────────
        mongo_client   = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        mongo_db       = mongo_client['HMS']
        refund_col     = mongo_db['hospital_investrefund']
        invest_col     = mongo_db['hospital_investbilling']

        # ── Verify the source invest bill exists and is active ───────────────
        invest_bill_no = data['investBillNo']
        source_bill = invest_col.find_one(
            {'investBillNo': invest_bill_no, 'is_active': True}
        )
        if not source_bill:
            return Response(
                {'error': f'Active invest bill not found: {invest_bill_no}'},
                status=drf_status.HTTP_404_NOT_FOUND
            )
        if source_bill.get("is_delete_requested"):
            return Response(
                {'error': 'Delete is pending approval for this bill.'},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        # ── Financial year prefix ────────────────────────────────────────────
        today = datetime.today()
        if today.month < 4:
            financial_year = f"{(today.year - 1) % 100:02d}{today.year % 100:02d}"
        else:
            financial_year = f"{today.year % 100:02d}{(today.year + 1) % 100:02d}"

        # fixed — financial year only
        bill_type  = data['bill_type']   
        prefix_key = f"{financial_year}"   # e.g. "2627"
        prefix     = f"{prefix_key}"      # e.g. "2627/"

        # ── Last-incremental refundBillNo (no atomic counter) ────────────────
        # Find the highest existing refundBillNo for this prefix and add 1.
       # Match only well-formed numbers: prefix + exactly 6 digits
        last_doc = refund_col.find_one(
            {'refundBillNo': {'$regex': f'^{re.escape(prefix)}\\d{{6}}$'}},
            sort=[('refundBillNo', -1)]
        )

        last_seq = 0
        if last_doc and last_doc.get('refundBillNo'):
            try:
                last_seq = int(last_doc['refundBillNo'][len(prefix):])
            except (ValueError, IndexError):
                last_seq = 0

        next_seq       = last_seq + 1
        refund_bill_no = f"{prefix}{next_seq:06d}"   # e.g. "2627000006"

        # ── Build document ───────────────────────────────────────────────────
        now = timezone.now()
        # Parse investBillDate string → proper datetime object
        raw_invest_date = data.get('investBillDate')
        if raw_invest_date:
            try:
                # Handle both "2026-05-13T11:57:04.604Z" and "2026-05-13T11:57:04.604+00:00"
                invest_bill_date = datetime.fromisoformat(
                    raw_invest_date.replace('Z', '+00:00')
                )
            except (ValueError, AttributeError):
                invest_bill_date = now
        else:
            invest_bill_date = now

        refund_doc = {
            'refundBillNo':     refund_bill_no,
            'refundBillDate':   now,
            'investBillNo':     invest_bill_no,
            'uhid':             data.get('uhid', ''),
            'ipNumber':         data.get('ipNumber', ''),
            'bill_type':        bill_type,
            'billTypeNo':       data.get('billTypeNo', ''),
            'refund_finalPrice':str(data.get('refund_finalPrice', '0.00')),
            'paymentStatus':    'Pending',
            'item':             item_data,
            'refundRemarks': data.get('refundRemarks', ''), 
            'investBillDate':   invest_bill_date,   # use the parsed datetime object
            'created_by':       current_user,
            'branch_code':      branch_code,
            'outlet_code':      outlet_code,
            'hospital_code':    hospital_code,
            'created_date':     now,
            'lastmodified_by':  None,
            'lastmodified_date':now,
            'is_approved':      False,
            'approved_by':      None,          
            'approved_date':    None,           
            'is_active':        True,
        }

        refund_col.insert_one(refund_doc)

        return Response(
            {
                'message':       'Refund bill created successfully!',
                'refundBillNo':  refund_bill_no,
            },
            status=drf_status.HTTP_201_CREATED
        )

    except Exception as e:
        traceback.print_exc()
        return Response(
            {'error': 'Refund creation failed', 'details': repr(e)},
            status=500
        )
    finally:
        if mongo_client:
            mongo_client.close()  