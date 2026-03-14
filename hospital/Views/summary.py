from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from ..models import Summary
from ..serializers import SummarySerializer
from django.shortcuts import render
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from rest_framework.parsers import MultiPartParser, FormParser
from bson import Decimal128
from rest_framework.decorators import api_view, permission_classes
from django.views.decorators.csrf import csrf_exempt
from pymongo import MongoClient
import os, json
from ..serializers import  Patient,PatientSerializer
from ..models import CTReport, MRIReport, USGReport, XRayReport
from ..serializers import   PatientSerializer
from ..serializers import   VendorSerializer
from ..models import RadiologyReport
from django.views.decorators.http import require_http_methods
import logging
logger = logging.getLogger(__name__)
from pymongo import MongoClient
from datetime import datetime
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
import json
from urllib.parse import unquote
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
import base64
from bson import ObjectId
import gridfs

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def summary_type(request):
    """Get list of active summary types from hospital_summarytype collection"""
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        summary_collection = hms_db['hospital_summarytype']

        summary_types = list(summary_collection.find(
            {"is_active": True},                           # filter
            {"_id": 0, "summaryNo": 1, "summaryType": 1}  # projection
        ))

        return Response(summary_types, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    finally:
        client.close()

from datetime import datetime

from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId
import json

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_summaries(request):
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        summary_collection  = hms_db['hospital_summary']
        patient_collection  = hms_db['hospital_patient']

        # Base filter
        query = {"is_active": True}

        # From / To date filter
        from_date = request.query_params.get('fromDate', '').strip()
        to_date   = request.query_params.get('toDate', '').strip()

        if from_date or to_date:
            date_filter = {}
            if from_date:
                date_filter['$gte'] = datetime.strptime(from_date, '%Y-%m-%d')
            if to_date:
                to_dt = datetime.strptime(to_date, '%Y-%m-%d')
                date_filter['$lte'] = to_dt.replace(hour=23, minute=59, second=59)
            query['date'] = date_filter

        # Summary type filter
        summary_type = request.query_params.get('summaryType', '').strip()
        if summary_type:
            query['summaryType'] = {'$regex': summary_type, '$options': 'i'}

        summaries = list(summary_collection.find(query, {"_id": 0}))

        if summaries:
            # Collect unique UHIDs from all summaries
            uhids = list({s['uhid'] for s in summaries if s.get('uhid')})

            # Fetch all matching patients in a single query
            patients = patient_collection.find(
                {"uhid": {"$in": uhids}},
                {"_id": 0, "uhid": 1, "salutation": 1, "firstName": 1, "lastName": 1}
            )

            # Build a lookup map: uhid → full name
            patient_map = {}
            for p in patients:
                full_name = f"{p.get('salutation', '')} {p.get('firstName', '')} {p.get('lastName', '')}".strip()
                patient_map[p['uhid']] = full_name

            # Attach patient name to each summary
            for s in summaries:
                uhid = s.get('uhid', '')
                s['patient'] = patient_map.get(uhid, s.get('patient', ''))

        return Response(summaries, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    finally:
        if client:
            client.close()


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_summary(request):
    data = request.data.copy()

    # Strip time from date — model is DateField, frontend sends full ISO datetime
    if data.get('date'):
        data['date'] = str(data['date'])[:10]  # "2026-02-23T07:42:44.007Z" → "2026-02-23"

    serializer = SummarySerializer(data=data)
    if serializer.is_valid():
        ip_no = serializer.validated_data.get('ipNo')

        if Summary.objects.filter(ipNo=ip_no).exists():
            return Response(
                {"error": f"Summary already exists for ipNo: {ip_no}"},
                status=status.HTTP_409_CONFLICT
            )

        created_by = request.data.get('auth-user-id', "system")
        branch_code = request.data.get('auth-branch-code', "system")
        department_code = request.data.get('auth-department-code', "system")
        hospital_code = request.data.get('auth-hospital-code', "system")

        instance = serializer.save(            
            branch_code=branch_code,
            department_code=department_code,
            hospital_code=hospital_code,
            created_by=created_by,
            created_date=datetime.utcnow()
        )

        return Response(
            {"message": "Summary created successfully", "ipNo": instance.ipNo},
            status=status.HTTP_201_CREATED
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@require_http_methods(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_patient_investigations(request, ip_no):
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        investbilling_collection      = hms_db['hospital_investbilling']
        investigationprice_collection = hms_db['hospital_investigationprice']
        radiology_collection          = hms_db['hospital_radiologyreport']  # direct mongo collection

        # ── Step 1: Get investBillNos for this IP ────────────────────────────
        invest_bills = list(investbilling_collection.find(
            {'ipNumber': ip_no, 'is_active': True},
            {'investBillNo': 1, '_id': 0}
        ))        

        if not invest_bills:
            return JsonResponse([], safe=False)

        invest_bill_nos = [b['investBillNo'] for b in invest_bills]       

        # ── Step 2: Query RadiologyReport directly via MongoDB ───────────────
        radiology_reports = list(radiology_collection.find(
            {
                'investBillNo': {'$in': invest_bill_nos},
                'is_active': True
            },
            {
                'investBillNo': 1,
                'billTypeNo': 1,
                'itemName': 1,
                'impression': 1,
                'is_approved': 1,
                'date': 1,
                '_id': 0
            }
        ))       

        if not radiology_reports:
            return JsonResponse([], safe=False)

       # ── Step 3: Get BillType labels from hospital_investigationprice ──────
        bill_type_nos = list({r['billTypeNo'] for r in radiology_reports})       

        price_records = list(investigationprice_collection.find(
            {'billTypeNo': {'$in': bill_type_nos}, 'is_active': True},  # added is_active
            {'billTypeNo': 1, 'BillType': 1, '_id': 0}
        ))       

        bill_type_label = {p['billTypeNo']: p['BillType'] for p in price_records}

        # ── Step 4: Build final response ──────────────────────────────────────
        all_reports = []
        for report in radiology_reports:
            bill_type_no = report.get('billTypeNo', '')
            report_type  = bill_type_label.get(bill_type_no, bill_type_no)

            all_reports.append({
                'reportType':    report_type,
                'investigation': report.get('itemName', ''),
                'impression':    report.get('impression', ''),
                'is_approved':   report.get('is_approved', False),
                'investBillNo':  report.get('investBillNo', ''),
                'billTypeNo':    bill_type_no,
            })
       
        return JsonResponse(all_reports, safe=False)

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'error': str(e), 'type': type(e).__name__}, status=500)

    finally:
        if client:
            client.close()   

@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def approve_summary(request, ip_no):
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_summary']  # Changed collection name to 'hospital_summary'
    try:
        # Get the user who is performing the soft delete (if available)
        created_by = request.data.get('auth-user-id', "system")

        
        # Find the summary by IP number and update
        result = collection.update_one(
            {"ipNo": ip_no},  # Query to find the document by IP No
            {"$set": {
                "approve": True,
                "approved_by": created_by,
                "approve_time": datetime.now().isoformat()  # Set the current time
            }}
        )
        
        # Check if the document was updated
        if result.matched_count > 0:
            return Response({"message": "Summary approved successfully"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Summary not found"}, status=status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PATCH'])  # Changed from DELETE to PATCH
@permission_classes([HasRoleAndDataPermission])
def delete_summary(request, ip_no):
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_summary']
    
    try:
        # Get the user who is performing the soft delete (if available)
        created_by = request.data.get('auth-user-id', "system")

        
        # Update the document to set is_active to False
        result = collection.update_one(
            {"ipNo": ip_no, "is_active": True},  # Only update if currently active
            {
                "$set": {
                    "is_active": False,
                    "deleted_by": created_by,
                    "deleted_date": datetime.now()
                }
            }
        )
        
        # Check if the document was updated
        if result.matched_count > 0:
            return Response(
                {"message": "Summary deleted successfully"}, 
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"error": "Summary not found or already deleted"}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    except Exception as e:
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    finally:
        client.close()  # Always close the MongoDB connection
    

from urllib.parse import unquote

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_editsummary(request, ip_no):
    from datetime import timezone, timedelta

    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        summary_collection = db['hospital_summary']
        patient_collection = db['hospital_patient']

        decoded_ip_no = unquote(ip_no)
        summary = summary_collection.find_one({"ipNo": decoded_ip_no})

        if not summary:
            return Response({"error": "Summary not found"}, status=status.HTTP_404_NOT_FOUND)

        summary['_id'] = str(summary['_id'])

        IST = timezone(timedelta(hours=5, minutes=30))

        def fmt_date_only(value):
            if not value:
                return None
            if isinstance(value, str):
                return value[:10]
            if isinstance(value, datetime):
                return value.replace(tzinfo=timezone.utc).astimezone(IST).strftime("%Y-%m-%d")
            return None

        def fmt_datetime(value):
            """Full datetime fields — convert UTC to IST."""
            if not value:
                return None, None
            if isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return value, None
            if isinstance(value, datetime):
                value = value.replace(tzinfo=timezone.utc).astimezone(IST)
                return value.strftime("%Y-%m-%d"), value.strftime("%H:%M")
            return None, None

        def fmt_time_only(value):
            """Time-only fields stored as datetime epoch — extract HH:MM without timezone shift."""
            if not value:
                return None
            if isinstance(value, datetime):
                return value.strftime("%H:%M")  # no IST conversion
            if isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return value.strftime("%H:%M")
                except ValueError:
                    return value
            return None

        # ── Summary created date ──
        date_str, date_time_str = fmt_datetime(summary.get('date'))
        summary['date']     = date_str
        summary['dateTime'] = date_time_str

        # ── DOA (plain string already) ──
        summary['doa'] = summary.get('doa', '')

        # ── DOA Time (time-only epoch — no IST shift) ──
        summary['doaTime'] = fmt_time_only(summary.get('doaTime')) or ""

        # ── DOD ──
        summary['dod'] = fmt_date_only(summary.get('dod'))

        # ── DOD Time (time-only epoch — no IST shift) ──
        summary['dodTime'] = fmt_time_only(summary.get('dodTime')) or "17:00"

        # ── Surgery Date ──
        summary['surgeryDate'] = fmt_date_only(summary.get('surgeryDate'))

        # ── Next Review Date ──
        summary['nextReviewDate'] = fmt_date_only(summary.get('nextReviewDate'))

        # ── Approve time ──
        ap_date, ap_time = fmt_datetime(summary.get('approve_time'))
        summary['approve_time']      = ap_date
        summary['approve_time_time'] = ap_time

        # ── Patient details from hospital_patient ──
        uhid = summary.get('uhid', '')
        if uhid:
            patient = patient_collection.find_one(
                {"uhid": uhid},
                {"_id": 0, "salutation": 1, "firstName": 1, "lastName": 1,
                 "age": 1, "gender": 1, "area": 1, "city": 1, "state": 1}
            )
            if patient:
                full_name = f"{patient.get('salutation', '')} {patient.get('firstName', '')} {patient.get('lastName', '')}".strip()
                full_address = ", ".join(p for p in [patient.get('area'), patient.get('city'), patient.get('state')] if p)
                summary['patient'] = full_name
                summary['age']     = patient.get('age', '')
                summary['gender']  = patient.get('gender', '')
                summary['address'] = full_address

        return Response(summary, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    finally:
        if client:
            client.close()

@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_summary_fields(request, ip_no):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_summary']

    try:
        decoded_ip_no = unquote(ip_no)
        lastmodified_by = request.data.get('auth-user-id', "system")

        # Fields to never update
        exclude_keys = {
            # Immutable / auth fields
            '_id', 'created_by', 'created_date',
            'lastmodified_date', 'lastmodified_by',
            # Strip ALL auth-* keys
            *[k for k in request.data.keys() if k.startswith('auth-')],
            # Frontend-only state fields not stored in DB
            'notes', 'currentField', 'dateTime', 'dateTime',
            'approve_time_time', 'selectedDiseases',
            # Patient info fetched from hospital_patient — not stored in summary
            'patient', 'age', 'gender', 'address',
        }

        data = {k: v for k, v in request.data.items() if k not in exclude_keys}

        if 'fieldsData' not in data or not data['fieldsData']:
            return Response({"error": "No fieldsData provided"}, status=status.HTTP_400_BAD_REQUEST)

        # Ensure fieldsData is stored as JSON string
        if isinstance(data['fieldsData'], dict):
            data['fieldsData'] = json.dumps(data['fieldsData'])

        def to_date(value):
            """'YYYY-MM-DD' string → datetime at midnight UTC (for DateField)."""
            if not value:
                return None
            try:
                return datetime.strptime(str(value)[:10], "%Y-%m-%d")
            except ValueError:
                return None

        def to_time(value):
            """'HH:MM' string → datetime(1900,1,1,H,M) (for TimeField)."""
            if not value:
                return None
            try:
                h, m = map(int, str(value).split(":"))
                return datetime(1900, 1, 1, h, m, 0)
            except (ValueError, AttributeError):
                return None

        # DateField columns → datetime at midnight
        for field in ('doa', 'dod', 'surgeryDate', 'nextReviewDate', 'date'):
            if field in data:
                data[field] = to_date(data[field])

        # TimeField columns → epoch datetime
        for field in ('doaTime', 'dodTime'):
            if field in data:
                data[field] = to_time(data[field])

        # Only set lastmodified_* from auth
        data['lastmodified_date'] = datetime.utcnow()
        data['lastmodified_by']   = lastmodified_by

        updated = collection.update_one(
            {"ipNo": decoded_ip_no},
            {"$set": data}
        )

        if updated.matched_count > 0:
            return Response({"message": "Summary updated successfully!"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Summary not found"}, status=status.HTTP_404_NOT_FOUND)

    except json.JSONDecodeError as e:
        return Response({"error": f"Invalid JSON in fieldsData: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        client.close()

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_printsummary(request, ip_no):
    decoded_ip_no = unquote(ip_no)

    try:
        client         = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db         = client['HMS']
        diagnostics_db = client['Diagnostics']
        global_db      = client['Global']

        # Collections
        core_testdetails_collection = diagnostics_db['core_testdetails']
        profile_collection          = global_db['backend_diagnostics_profile']
        fs                          = gridfs.GridFS(global_db)

        # ── STEP 1: Hospital summary ──────────────────────────────────────────
        summary = hms_db['hospital_summary'].find_one({"ipNo": decoded_ip_no})
        if not summary:
            client.close()
            return JsonResponse(
                {'error': 'Hospital summary not found for the given IP number'},
                status=404
            )
        summary['_id'] = str(summary['_id'])

        # ── STEP 2: Patient info from hospital_patient ────────────────────────
        uhid           = summary.get('uhid')
        patient_record = None

        if uhid:
            patient_record = hms_db['hospital_patient'].find_one({"uhid": uhid})
        if not patient_record:
            patient_record = hms_db['hospital_patient'].find_one(
                {"ip_number": decoded_ip_no}
            )

        if patient_record:
            salutation = (patient_record.get('salutation') or '').strip()
            first_name = (patient_record.get('firstName')  or '').strip()
            last_name  = (patient_record.get('lastName')   or '').strip()
            full_name  = ' '.join(filter(None, [salutation, first_name, last_name]))

            addr_parts = [
                patient_record.get('permanent_address') or '',
                patient_record.get('area')              or '',
                patient_record.get('city')              or '',
                patient_record.get('state')             or '',
            ]
            full_address = ', '.join(p for p in addr_parts if p)

            summary['patient']     = full_name   or summary.get('patient', '')
            summary['age']         = patient_record.get('age')    or summary.get('age', '')
            summary['gender']      = patient_record.get('gender') or summary.get('gender', '')
            summary['mobilePhone'] = patient_record.get('mobilePhone', '')
            summary['address']     = full_address or summary.get('address', '')
        else:
            summary.setdefault('mobilePhone', '')
            summary.setdefault('address', summary.get('address', ''))

        # Guarantee gender is always a string
        if not summary.get('gender'):
            summary['gender'] = ''

        # Init test fields
        summary['testdetails']  = []
        summary['barcode']      = None
        summary['investBillNo'] = None
        summary['signatures']   = []

        # ── STEP 3: Get barcode from core_hmsbarcode by ipnumber ──────────────
        barcode_record = diagnostics_db['core_hmsbarcode'].find_one(
            {"ipnumber": decoded_ip_no}
        )
        if not barcode_record:
            client.close()
            return JsonResponse(summary, safe=False)

        barcode                 = barcode_record.get('barcode')
        summary['barcode']      = barcode
        summary['investBillNo'] = barcode_record.get('billnumber')

        if not barcode:
            client.close()
            return JsonResponse(summary, safe=False)

        # ── STEP 4: Fetch standard test result documents from core_testvalue ──
        test_value_records = list(
            diagnostics_db['core_testvalue'].find({"barcode": barcode})
        )

        # ── Helper: get parameter definition from core_testdetails ────────────
        def get_parameter_from_core(core_test, device_id, test_code=None, param_index=None):
            """
            Match a parameter definition from core_testdetails.
            Supports both dict (device_id-keyed) and list formats.
            Uses param_index for accuracy; falls back to test_code match.
            """
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

        # ── Helper: fetch employee signature ──────────────────────────────────
        def get_employee_signature_data(employee_id):
            if not employee_id:
                return None
            try:
                profile = profile_collection.find_one({"employeeId": employee_id})
                if not profile:
                    return None

                employee_name       = profile.get("employeeName", "")
                designation         = profile.get("designation", "")
                signature_file_id   = profile.get("signatureFileId")
                signature_base64    = None

                if signature_file_id:
                    try:
                        if isinstance(signature_file_id, str):
                            signature_file_id = ObjectId(signature_file_id)
                        sig_file         = fs.get(signature_file_id)
                        signature_base64 = base64.b64encode(sig_file.read()).decode('utf-8')
                    except Exception as e:
                        print(f"Signature fetch error for {employee_id}: {e}")

                return {
                    "employeeName":    employee_name,
                    "designation":     designation,
                    "signatureBase64": signature_base64
                }
            except Exception as e:
                print(f"Employee data error for {employee_id}: {e}")
                return None

        # ── STEP 5: Parse & enrich STANDARD test details ──────────────────────
        test_details   = []
        lab_approvers  = set()   # approvers from standard core_testvalue
        micro_approvers = set()  # approvers from core_mbtestvalue

        for test_value in test_value_records:
            try:
                raw     = test_value.get('testdetails', '[]')
                details = json.loads(raw) if isinstance(raw, str) else raw

                if not isinstance(details, list):
                    continue

                for test in details:

                    # Only include APPROVED tests
                    if test.get("approve") is not True:
                        continue

                    test_id     = test.get("test_id")
                    device_id   = test.get("device_id", "N/A")
                    parameters  = test.get("parameters", [])
                    approve_by  = test.get("approve_by", "")
                    verified_by = test.get("verified_by", "N/A")
                    approve_time  = test.get("approve_time", "N/A")
                    dispatch_time = test.get("dispatch_time", "")
                    outsourced    = test.get("outsourced", False)
                    comment       = test.get("comment", "")
                    remarks       = test.get("remarks", "")

                    if approve_by:
                        lab_approvers.add(approve_by)
                    core_test = core_testdetails_collection.find_one({"test_id": test_id})

                    if core_test:
                        testname      = core_test.get("test_name", test.get("testname", ""))
                        department    = core_test.get("department", "N/A")
                        NABL          = core_test.get("NABL", False)
                        specimen_type = core_test.get("specimen_type", "N/A")
                    else:
                        testname      = test.get("testname", "")
                        department    = test.get("department", "N/A")
                        NABL          = test.get("NABL", False)
                        specimen_type = test.get("specimen_type", "N/A")

                    test_detail = {
                        "test_id":        test_id,
                        "department":     department,
                        "NABL":           NABL,
                        "outsourced":     outsourced,
                        "comment":        comment,
                        "remarks":        remarks,
                        "testname":       testname,
                        "verified_by":    verified_by,
                        "approve_by":     approve_by,
                        "approve_time":   approve_time,
                        "dispatch_time":  dispatch_time,
                        "is_microbiology": False,  # Flag: standard test
                    }

                    if parameters and len(parameters) > 0 and core_test:
                        enriched_parameters = []

                        for param_index, param_value in enumerate(parameters):
                            test_code     = param_value.get("test_code")
                            value         = param_value.get("value", "")
                            param_comment = param_value.get("comment", "")

                            param_def = get_parameter_from_core(
                                core_test,
                                device_id,
                                test_code=test_code,
                                param_index=param_index
                            )

                            if param_def:
                                enriched_parameters.append({
                                    "name":            param_def.get("test_name", ""),
                                    "test_code":       test_code,
                                    "value":           value,
                                    "unit":            param_def.get("unit", ""),
                                    "reference_range": param_def.get("reference_range", ""),
                                    "method":          param_def.get("method", ""),
                                    "specimen_type":   specimen_type,
                                    "sub_title":       param_def.get("sub_title", ""),
                                    "value_option":    param_def.get("value_option", []),
                                    "comment":         param_comment,
                                })
                            else:
                                enriched_parameters.append({
                                    "name":            param_value.get("name", "N/A"),
                                    "test_code":       test_code,
                                    "value":           value,
                                    "unit":            param_value.get("unit", "N/A"),
                                    "reference_range": param_value.get("reference_range", "N/A"),
                                    "method":          param_value.get("method", "N/A"),
                                    "specimen_type":   specimen_type,
                                    "sub_title":       param_value.get("sub_title", ""),
                                    "value_option":    [],
                                    "comment":         param_comment,
                                })

                        test_detail["parameters"] = enriched_parameters

                    elif parameters and len(parameters) > 0:
                        test_detail["parameters"] = parameters

                    else:
                        if core_test:
                            test_detail.update({
                                "method":          core_test.get("method", ""),
                                "specimen_type":   specimen_type,
                                "value":           test.get("value", ""),
                                "unit":            core_test.get("unit", ""),
                                "reference_range": core_test.get("reference_range", ""),
                                "sub_title":       test.get("sub_title", ""),
                            })
                        else:
                            test_detail.update({
                                "method":          test.get("method", ""),
                                "specimen_type":   test.get("specimen_type", ""),
                                "value":           test.get("value", ""),
                                "unit":            test.get("unit", ""),
                                "reference_range": test.get("reference_range", ""),
                                "sub_title":       test.get("sub_title", ""),
                            })

                    test_details.append(test_detail)

            except (json.JSONDecodeError, AttributeError):
                continue

        # ── STEP 6: Fetch MICROBIOLOGY tests from core_mbtestvalue (MongoDB) ────
        mb_testvalue_collection = diagnostics_db['core_mbtestvalue']
        mb_test_value_records   = list(mb_testvalue_collection.find({"barcode": barcode}))

        for mb_record in mb_test_value_records:
            try:
                mb_details = mb_record.get('testdetails', [])
                if isinstance(mb_details, str):
                    try:
                        mb_details = json.loads(mb_details)
                    except (json.JSONDecodeError, ValueError):
                        mb_details = []

                if not isinstance(mb_details, list):
                    mb_details = []

                for test in mb_details:
                    # Only include approved tests
                    if test.get("approve") is not True:
                        continue

                    test_id      = test.get("test_id")
                    approve_by   = test.get("approve_by", "")
                    verified_by  = test.get("verified_by", "N/A")
                    approve_time = test.get("approve_time", "N/A")
                    comment      = test.get("comment", "")
                    remarks      = test.get("remarks", "")
                    colony_count = test.get("colony_count", "")
                    parameter_type = test.get("parameter_type", "N/A")

                    if approve_by:
                        micro_approvers.add(approve_by)

                    # Fetch core test definition from core_testdetails (for MB)
                    core_test = core_testdetails_collection.find_one({"test_id": test_id})

                    if core_test:
                        testname      = core_test.get("test_name", test.get("testname", ""))
                        department    = core_test.get("department", "Microbiology")
                        specimen_type = core_test.get("specimen_type", "N/A")
                        is_AG_title   = core_test.get("is_AG_title", False)
                    else:
                        testname      = test.get("testname", "")
                        department    = test.get("department", "Microbiology")
                        specimen_type = test.get("specimen_type", "N/A")
                        is_AG_title   = test.get("is_AG_title", False)

                    # Build microbiology test detail (matches handlePrint MB format)
                    mb_test_detail = {
                        "test_id":         test_id,
                        "testname":        testname,
                        "department":      department,
                        "specimen_type":   specimen_type,
                        "is_AG_title":     is_AG_title,
                        "remarks":         remarks,
                        "colony_count":    colony_count,
                        "comment":         comment,
                        "verified_by":     verified_by,
                        "approve_by":      approve_by,
                        "approve_time":    approve_time,
                        "is_microbiology": True,  # Flag for frontend renderer
                    }

                    # Process parameters (antibiogram rows)
                    raw_parameters = test.get("parameters", [])
                    if raw_parameters and len(raw_parameters) > 0 and core_test:
                        simplified_parameters = []

                        for param_index, param_value in enumerate(raw_parameters):
                            test_code     = param_value.get("test_code")
                            value         = param_value.get("value", "")
                            result        = param_value.get("result", "")
                            param_comment = param_value.get("comment", "")

                            # Get parameter definition using index-based matching
                            param_def = get_parameter_from_core(
                                core_test,
                                parameter_type,
                                test_code=test_code,
                                param_index=param_index
                            )

                            if param_def:
                                simplified_parameters.append({
                                    "test_name": param_def.get("test_name", ""),
                                    "test_code": test_code,
                                    "value":     value,   # zone of inhibition
                                    "result":    result,  # S / R / I
                                    "comment":   param_comment,
                                })
                            else:
                                simplified_parameters.append({
                                    "test_name": param_value.get("name", "N/A"),
                                    "test_code": test_code,
                                    "value":     value,
                                    "result":    result,
                                    "comment":   param_comment,
                                })

                        mb_test_detail["parameters"] = simplified_parameters

                    elif raw_parameters and len(raw_parameters) > 0:
                        # No core_test found — use raw data
                        simplified_parameters = []
                        for param_value in raw_parameters:
                            simplified_parameters.append({
                                "test_name": param_value.get("name", "N/A"),
                                "test_code": param_value.get("test_code", ""),
                                "value":     param_value.get("value", ""),
                                "result":    param_value.get("result", ""),
                                "comment":   param_value.get("comment", ""),
                            })
                        mb_test_detail["parameters"] = simplified_parameters
                    else:
                        mb_test_detail["parameters"] = []

                    test_details.append(mb_test_detail)

            except (json.JSONDecodeError, AttributeError, Exception) as e:
                print(f"Error processing MBTestValue record: {e}")
                continue

        summary['testdetails'] = test_details

        # ── STEP 7: Fetch approver signatures separately ───────────────────────
        # Lab (standard) signatures
        signatures = []
        for approver_id in lab_approvers:
            sig_data = get_employee_signature_data(approver_id)
            if sig_data:
                signatures.append(sig_data)

        # Microbiology signatures (kept separate so frontend can render them independently)
        micro_signatures = []
        for approver_id in micro_approvers:
            sig_data = get_employee_signature_data(approver_id)
            if sig_data:
                micro_signatures.append(sig_data)

        summary['signatures']       = signatures        # for standard lab sections
        summary['micro_signatures'] = micro_signatures  # for microbiology section

        client.close()
        return JsonResponse(summary, safe=False)

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)