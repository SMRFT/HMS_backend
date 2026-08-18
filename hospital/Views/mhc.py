from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
from datetime import datetime, timedelta
from django.utils import timezone
from bson import ObjectId
import pytz
import os
import json
import logging

logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')


def _to_ist(dt):
    if not dt or not isinstance(dt, datetime):
        return dt
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(IST).strftime('%Y-%m-%d %I:%M %p')


def _parse_slot_datetime(raw_val):
    if not raw_val:
        return None
    try:
        normalized = raw_val.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return None


def _serialize_report(doc):
    if not doc:
        return None
    if '_id' in doc:
        doc['id'] = str(doc['_id'])
        doc['_id'] = str(doc['_id'])
    for field in ['date', 'created_date', 'lastmodified_date', 'approved_date',
                  'deleted_date', 'patientIn_DateTime', 'scan_started_DateTime', 'dispatch_DateTime']:
        if field in doc and isinstance(doc[field], datetime):
            doc[field] = _to_ist(doc[field])
    if 'slot_DateTime' in doc and isinstance(doc['slot_DateTime'], datetime):
        doc['slot_DateTime'] = doc['slot_DateTime'].strftime('%Y-%m-%dT%H:%M:%S')
    return doc


# ════════════════════════════════════════════════════════════════════════════
#  GET  /mhc-investigations/   → list all PACK / MHC patient bills
# ════════════════════════════════════════════════════════════════════════════
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_mhc_investigations(request):
    """
    Fetch patient investigations where billTypeNo == 'PACK'
    """
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    invest_bill_no_filter = request.GET.get('investBillNo')
    package_id_filter = request.GET.get('package_id')
    uhid_filter = request.GET.get('uhid')

    branch_code = request.data.get('auth-branch-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    global_db = client['Global']

    invest_billing_coll = db['hospital_investbilling']
    mhc_report_coll = db['hospital_mhcreport']
    patient_coll = db['hospital_patient']
    package_coll = db['hospital_package']
    refund_coll = db['hospital_investrefund']
    diagnostics_profile_coll = global_db['backend_diagnostics_profile']

    try:
        # 1. Billing Query
        billing_filter = {'billTypeNo': 'PACK', 'is_active': True}

        if hospital_code:
            billing_filter['hospital_code'] = hospital_code
        if branch_code:
            billing_filter['branch_code'] = branch_code
        if invest_bill_no_filter:
            billing_filter['investBillNo'] = invest_bill_no_filter
        if uhid_filter:
            billing_filter['uhid'] = uhid_filter
        if package_id_filter:
            try:
                pkg_id_num = int(package_id_filter)
                billing_filter['$or'] = [
                    {'package_id': pkg_id_num},
                    {'package_id': str(pkg_id_num)},
                    {'Package_id': pkg_id_num},
                    {'Package_id': str(pkg_id_num)},
                ]
            except ValueError:
                billing_filter['package_id'] = package_id_filter

        if from_date or to_date:
            date_filter = {}
            if from_date:
                try:
                    date_filter['$gte'] = datetime.strptime(from_date, '%Y-%m-%d')
                except ValueError:
                    return JsonResponse({'error': 'Invalid from_date format'}, status=400)
            if to_date:
                try:
                    to_date_obj = datetime.strptime(to_date, '%Y-%m-%d')
                    date_filter['$lte'] = to_date_obj + timedelta(days=1) - timedelta(seconds=1)
                except ValueError:
                    return JsonResponse({'error': 'Invalid to_date format'}, status=400)
            billing_filter['investBillDate'] = date_filter

        billing_records = list(invest_billing_coll.find(billing_filter, {'_id': 0}).sort('investBillDate', -1))
        if not billing_records:
            return JsonResponse([], safe=False)

        # 2. Batch Refund Cache
        invest_bill_nos = [r.get('investBillNo') for r in billing_records if r.get('investBillNo')]
        refunded_bills = set()
        if invest_bill_nos:
            refund_docs = refund_coll.find(
                {'investBillNo': {'$in': invest_bill_nos}, 'is_active': True},
                {'_id': 0, 'investBillNo': 1}
            )
            for rdoc in refund_docs:
                if rdoc.get('investBillNo'):
                    refunded_bills.add(rdoc['investBillNo'])

        # 3. Batch Reports
        report_filter = {'investBillNo': {'$in': invest_bill_nos}, 'is_active': True}
        if hospital_code:
            report_filter['hospital_code'] = hospital_code
        if branch_code:
            report_filter['branch_code'] = branch_code

        mhc_reports = list(mhc_report_coll.find(report_filter, {'_id': 0}))
        report_map = {}
        for r in mhc_reports:
            for field in ['date', 'created_date', 'lastmodified_date', 'approved_date',
                          'deleted_date', 'patientIn_DateTime', 'scan_started_DateTime', 'dispatch_DateTime']:
                if field in r:
                    r[field] = _to_ist(r[field])

            bill_key = r.get('investBillNo')
            if bill_key:
                report_map[bill_key] = r

        # 4. Batch Patients (Comprehensive ORM + MongoDB Multi-Variant Lookup)
        uhid_list = list({str(r['uhid']).strip() for r in billing_records if r.get('uhid', '').strip()})
        patient_map = {}
        if uhid_list:
            # Build search variations (e.g. S026/00541, 00541, 541, s026/00541)
            search_tokens = set()
            for u in uhid_list:
                clean_u = u.strip()
                search_tokens.add(clean_u)
                search_tokens.add(clean_u.upper())
                search_tokens.add(clean_u.lower())
                import re
                nums = re.findall(r'\d+', clean_u)
                if nums:
                    num_str = nums[-1]
                    search_tokens.add(num_str)
                    search_tokens.add(num_str.lstrip('0'))

            # A. Query Django ORM Patient model
            try:
                from ..models import Patient
                from django.db.models import Q

                orm_q = Q(uhid__in=list(search_tokens))
                for u in uhid_list:
                    orm_q |= Q(uhid__iexact=u)
                    if '/' in u:
                        suf = u.split('/')[-1]
                        orm_q |= Q(uhid__iendswith=suf) | Q(uhid__iendswith=suf.lstrip('0'))

                orm_patients = Patient.objects.filter(orm_q)
                for p in orm_patients:
                    p_uhid = str(p.uhid).strip()
                    p_data = {
                        'uhid': p_uhid,
                        'salutation': getattr(p, 'salutation', '') or '',
                        'firstName': getattr(p, 'firstName', '') or '',
                        'lastName': getattr(p, 'lastName', '') or '',
                        'gender': getattr(p, 'gender', '') or '',
                        'age': getattr(p, 'age', '') or '',
                        'dob': getattr(p, 'dob', None),
                    }
                    patient_map[p_uhid] = p_data
                    patient_map[p_uhid.upper()] = p_data
                    patient_map[p_uhid.lower()] = p_data
                    if '/' in p_uhid:
                        suf = p_uhid.split('/')[-1]
                        patient_map[suf] = p_data
                        patient_map[suf.lstrip('0')] = p_data
            except Exception as e:
                logger.warning(f"Django Patient ORM lookup warning: {e}")

            # B. Query MongoDB hospital_patient collection
            try:
                mongo_patients = list(patient_coll.find({
                    'uhid': {'$in': list(search_tokens)}
                }))
                for p in mongo_patients:
                    p_uhid = str(p.get('uhid', '')).strip()
                    if p_uhid:
                        patient_map.setdefault(p_uhid, p)
                        patient_map.setdefault(p_uhid.upper(), p)
                        patient_map.setdefault(p_uhid.lower(), p)
                        if '/' in p_uhid:
                            suf = p_uhid.split('/')[-1]
                            patient_map.setdefault(suf, p)
                            patient_map.setdefault(suf.lstrip('0'), p)
            except Exception as e:
                logger.warning(f"MongoDB hospital_patient lookup warning: {e}")

        # 5. Batch Doctor / ReferredBy Cache
        all_profile_ids = set()
        for record in billing_records:
            doc_val = record.get('doctor', '')
            ref_val = record.get('referredBy', '')
            if doc_val and str(doc_val).upper() != 'SELF':
                all_profile_ids.add(str(doc_val))
            if ref_val and str(ref_val).upper() != 'SELF':
                all_profile_ids.add(str(ref_val))

        diagnostics_profile_cache = {}
        if all_profile_ids:
            profile_docs = diagnostics_profile_coll.find(
                {'employeeId': {'$in': list(all_profile_ids)}},
                {'_id': 0, 'employeeId': 1, 'employeeName': 1}
            )
            for p in profile_docs:
                emp_id = str(p.get('employeeId', ''))
                if emp_id:
                    diagnostics_profile_cache[emp_id] = p.get('employeeName', '')

        # 6. Batch Package Cache
        package_ids = set()
        for record in billing_records:
            pid = record.get('package_id') or record.get('Package_id')
            if pid:
                try:
                    package_ids.add(int(pid))
                except (ValueError, TypeError):
                    package_ids.add(pid)

        package_name_map = {}
        if package_ids:
            pkg_docs = package_coll.find(
                {'packageNo': {'$in': list(package_ids)}},
                {'_id': 0, 'packageNo': 1, 'packageName': 1}
            )
            for pdoc in pkg_docs:
                pno = pdoc.get('packageNo')
                if pno is not None:
                    package_name_map[pno] = pdoc.get('packageName', '')
                    package_name_map[str(pno)] = pdoc.get('packageName', '')

        # 7. Build Results
        result_rows = []
        for record in billing_records:
            bill_no = record.get('investBillNo', '')
            raw_uhid = str(record.get('uhid', '')).strip()

            # Multi-level patient lookup
            patient_doc = (
                patient_map.get(raw_uhid)
                or patient_map.get(raw_uhid.upper())
                or patient_map.get(raw_uhid.lower())
                or (patient_map.get(raw_uhid.split('/')[-1]) if '/' in raw_uhid else None)
                or (patient_map.get(raw_uhid.split('/')[-1].lstrip('0')) if '/' in raw_uhid else None)
                or {}
            )

            # Patient details priority: patient_doc -> billing record
            salutation = patient_doc.get('salutation') or record.get('salutation', '')
            first_name = patient_doc.get('firstName') or patient_doc.get('first_name') or record.get('firstName') or record.get('first_name', '')
            middle_name = patient_doc.get('middleName') or patient_doc.get('middle_name') or record.get('middleName', '')
            last_name = patient_doc.get('lastName') or patient_doc.get('last_name') or record.get('lastName') or record.get('last_name', '')
            gender = patient_doc.get('gender') or patient_doc.get('Gender') or record.get('gender') or record.get('Gender', '')
            age = record.get('age') or patient_doc.get('age', '')
            age_type = record.get('age_type') or patient_doc.get('age_type', 'Y')

            name_parts = [p for p in [salutation, first_name, middle_name, last_name] if p]
            built_name = " ".join(name_parts).strip()
            final_patient_name = (
                built_name
                or patient_doc.get('patient_name')
                or patient_doc.get('patientName')
                or patient_doc.get('name')
                or record.get('patientName')
                or record.get('patient_name')
                or record.get('name')
                or 'N/A'
            )

            # Package ID & Name
            raw_pkg_id = record.get('package_id') or record.get('Package_id') or ''
            try:
                pkg_id = int(raw_pkg_id) if raw_pkg_id != '' else ''
            except (ValueError, TypeError):
                pkg_id = raw_pkg_id

            pkg_name = package_name_map.get(pkg_id) or record.get('packageName') or f"Package #{pkg_id}" if pkg_id else "Health Check-up Package"

            # Doctor & ReferredBy
            doc_id = str(record.get('doctor', ''))
            ref_id = str(record.get('referredBy', ''))
            doctor_name = diagnostics_profile_cache.get(doc_id, doc_id) if doc_id.upper() != 'SELF' else 'SELF'
            referred_by_name = diagnostics_profile_cache.get(ref_id, ref_id) if ref_id.upper() != 'SELF' else 'SELF'

            # Report Status
            existing_report = report_map.get(bill_no)

            row = {
                'investBillNo': bill_no,
                'uhid': raw_uhid,
                'ipNumber': record.get('ipNumber', ''),
                'investBillDate': _to_ist(record.get('investBillDate')),
                'rawInvestBillDate': record.get('investBillDate').isoformat() if isinstance(record.get('investBillDate'), datetime) else record.get('investBillDate', ''),
                'billTypeNo': 'PACK',
                'billType': record.get('billType', 'Master Health Check-up'),
                'package_id': pkg_id,
                'packageName': pkg_name,
                'salutation': salutation,
                'firstName': first_name,
                'middleName': middle_name,
                'lastName': last_name,
                'patientName': final_patient_name,
                'gender': gender or 'N/A',
                'age': age,
                'age_type': age_type,
                'doctor': doc_id,
                'doctorName': doctor_name,
                'referredBy': ref_id,
                'referredByName': referred_by_name,
                'paymentMethod': record.get('paymentMethod', 'Cash'),
                'paymentStatus': record.get('paymentStatus', 'Pending'),
                'total': record.get('total', 0),
                'finalPrice': record.get('finalPrice', 0),
                'is_emergency': bool(record.get('is_emergency', False)),
                'items': record.get('item', []),
                'has_report': bool(existing_report and existing_report.get('has_report')),
                'is_approved': bool(existing_report and existing_report.get('is_approved')),
                'is_refunded': bill_no in refunded_bills,
                'report': existing_report or None,
            }

            # Attach review / next due date and check-in flags from report
            if existing_report:
                row['next_due_date'] = existing_report.get('next_due_date') or existing_report.get('next_review_date', '')
                row['patientIn_DateTime'] = existing_report.get('patientIn_DateTime')
                row['scan_started_DateTime'] = existing_report.get('scan_started_DateTime')
                row['dispatch_DateTime'] = existing_report.get('dispatch_DateTime')
                row['is_Dispatched'] = bool(existing_report.get('is_Dispatched') or existing_report.get('dispatch_DateTime'))
                row['impression'] = existing_report.get('impression', '')

            result_rows.append(row)

        return JsonResponse(result_rows, safe=False)

    except Exception as e:
        logger.exception("get_mhc_investigations failed")
        return JsonResponse({'error': str(e)}, status=500)
    finally:
        client.close()


# ════════════════════════════════════════════════════════════════════════════
#  GET  /mhc-reports/format/   → fetch schema from hospital_mhc_formats
# ════════════════════════════════════════════════════════════════════════════
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_mhc_format(request):
    """
    GET /mhc-reports/format/?package_id=...&gender=...
    Fetches format template from hospital_mhc_formats collection based on package_id.
    """
    package_id = request.GET.get('package_id')
    gender = request.GET.get('gender', '').strip().lower()

    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_mhc_formats']

    try:
        # Build query for package_id
        if not package_id:
            return JsonResponse({
                'success': False,
                'error': 'Package ID is required'
            }, status=400)

        query = {'is_active': True}
        try:
            pkg_num = int(package_id)
            query['$or'] = [
                {'package_id': pkg_num},
                {'package_id': str(pkg_num)},
                {'packageNo': pkg_num},
                {'packageNo': str(pkg_num)},
            ]
        except ValueError:
            query['package_id'] = package_id

        doc = collection.find_one(query)

        if not doc:
            return JsonResponse({
                'success': False,
                'error': 'There is no format for this package'
            }, status=404)

        # Extract gender-specific section or return whole object
        resolved_gender = 'female' if gender in ('female', 'f') else 'male'
        gender_data = doc.get(resolved_gender) or doc.get('male') or doc.get('female') or {}

        # Meta
        doc_id = str(doc.get('_id', ''))
        pkg_id_val = doc.get('package_id') or doc.get('packageNo') or package_id

        return JsonResponse({
            'success': True,
            '_id': doc_id,
            'package_id': pkg_id_val,
            'gender': resolved_gender,
            'sections': gender_data,
            'male': doc.get('male', {}),
            'female': doc.get('female', {}),
        })

    except Exception as e:
        logger.exception("get_mhc_format failed")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    finally:
        client.close()


# ════════════════════════════════════════════════════════════════════════════
#  POST  /mhc-reports/   → create/save MHC report
# ════════════════════════════════════════════════════════════════════════════
@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_mhc_report(request):
    """
    POST /mhc-reports/
    Creates or updates an MHC report in hospital_mhcreport.
    """
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_mhcreport']

    try:
        data = request.data
        user_id = data.get('auth-user-id', 'system')
        branch_code = data.get('auth-branch-code', 'SHB001')
        outlet_code = data.get('auth-outlet-code', 'OLET003')
        hospital_code = data.get('auth-hospital-code', 'SH001')

        invest_bill_no = data.get('investBillNo')
        if not invest_bill_no:
            return JsonResponse({"error": "investBillNo is required"}, status=400)

        uhid = data.get('uhid', '')
        package_id = data.get('package_id', '')
        package_name = data.get('packageName', '')
        impression = data.get('impression', '')
        valuedetails = data.get('valuedetails', {})

        # Extract or receive next_due_date (calculated next due date)
        next_due_date = data.get('next_due_date') or data.get('next_review_date') or ''
        if not next_due_date and isinstance(valuedetails, dict):
            srr = valuedetails.get('summary_of_review_and_recommendations')
            if isinstance(srr, list):
                for item in srr:
                    if item.get('test_code') == 'SRR03':
                        params = item.get('parameter', [])
                        for p in params:
                            if p.get('pm_code') == 'SRR03P02' or 'DATE' in p.get('pm_name', '').upper():
                                next_due_date = p.get('value', '')
                                break
            if not next_due_date:
                due_sec = valuedetails.get('next_master_health_check-up_due')
                if isinstance(due_sec, list):
                    for item in due_sec:
                        if item.get('test_code') == 'NMHCD02':
                            next_due_date = item.get('value', '')
                            break
                elif isinstance(due_sec, dict):
                    next_due_date = due_sec.get('NMHCD02', '')

        # Date Parsing
        raw_date = data.get('investBillDate')
        if raw_date:
            try:
                date_val = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                date_val = timezone.now()
        else:
            date_val = timezone.now()

        # Check existing report
        existing = collection.find_one({
            'investBillNo': invest_bill_no,
            'is_active': True,
        })

        if existing:
            set_payload = {
                'valuedetails': valuedetails,
                'impression': impression,
                'next_due_date': next_due_date,
                'has_report': True,
                'lastmodified_by': user_id,
                'lastmodified_date': timezone.now(),
            }
            if package_id:
                set_payload['package_id'] = package_id
            if package_name:
                set_payload['packageName'] = package_name

            collection.update_one({'_id': existing['_id']}, {
                '$set': set_payload,
                '$unset': {'slot_DateTime': ''}
            })
            updated = collection.find_one({'_id': existing['_id']})
            return JsonResponse({
                'id': str(existing['_id']),
                'investBillNo': invest_bill_no,
                'message': 'MHC Report updated successfully',
                'report': _serialize_report(updated),
            }, status=200)

        # Create new report
        new_doc = {
            'date': date_val,
            'investBillNo': invest_bill_no,
            'uhid': uhid,
            'package_id': package_id,
            'packageName': package_name,
            'billTypeNo': 'PACK',
            'valuedetails': valuedetails,
            'impression': impression,
            'next_due_date': next_due_date,
            'is_approved': False,
            'has_report': True,
            'is_active': True,
            'created_by': user_id,
            'created_date': timezone.now(),
            'lastmodified_by': None,
            'lastmodified_date': timezone.now(),
            'branch_code': branch_code,
            'outlet_code': outlet_code,
            'hospital_code': hospital_code,
        }

        result = collection.insert_one(new_doc)

        return JsonResponse({
            'id': str(result.inserted_id),
            'investBillNo': invest_bill_no,
            'message': 'MHC Report created successfully',
        }, status=201)

    except Exception as e:
        logger.exception("create_mhc_report failed")
        return JsonResponse({'error': str(e)}, status=400)
    finally:
        client.close()


# ════════════════════════════════════════════════════════════════════════════
#  GET  /mhc-reports/<investBillNo>/   → fetch report details
# ════════════════════════════════════════════════════════════════════════════
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_mhc_report_by_bill(request, investBillNo):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_mhcreport']

    try:
        report = collection.find_one({'investBillNo': investBillNo, 'is_active': True})
        if not report:
            return JsonResponse({'error': 'Report not found'}, status=404)

        return JsonResponse(_serialize_report(report), safe=False)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    finally:
        client.close()


# ════════════════════════════════════════════════════════════════════════════
#  PATCH  /mhc-reports/edit/<investBillNo>/   → edit report values
# ════════════════════════════════════════════════════════════════════════════
@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def edit_mhc_report(request, investBillNo):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_mhcreport']

    try:
        user_id = request.data.get('auth-user-id', 'system')
        new_impression = request.data.get('impression')
        new_valuedetails = request.data.get('valuedetails')

        report = collection.find_one({'investBillNo': investBillNo, 'is_active': True})
        if not report:
            return JsonResponse({'error': 'Report not found'}, status=404)

        update_payload = {
            'lastmodified_by': user_id,
            'lastmodified_date': timezone.now(),
        }
        if new_impression is not None:
            update_payload['impression'] = new_impression
        if new_valuedetails is not None:
            update_payload['valuedetails'] = new_valuedetails

        collection.update_one({'_id': report['_id']}, {'$set': update_payload})
        updated = collection.find_one({'_id': report['_id']})
        return JsonResponse(_serialize_report(updated), safe=False, status=200)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    finally:
        client.close()


# ════════════════════════════════════════════════════════════════════════════
#  PATCH  /mhc-reports/approve/<investBillNo>/   → approve report
# ════════════════════════════════════════════════════════════════════════════
@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def approve_mhc_report(request, investBillNo):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_mhcreport']

    try:
        user_id = request.data.get('auth-user-id', 'system')
        report = collection.find_one({'investBillNo': investBillNo, 'is_active': True})
        if not report:
            return JsonResponse({'error': 'Report not found'}, status=404)

        collection.update_one(
            {'_id': report['_id']},
            {'$set': {'is_approved': True, 'approved_by': user_id, 'approved_date': timezone.now()}}
        )
        updated = collection.find_one({'_id': report['_id']})
        return JsonResponse(_serialize_report(updated), safe=False, status=200)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    finally:
        client.close()


# ════════════════════════════════════════════════════════════════════════════
#  PATCH  /mhc-reports/delete/<investBillNo>/   → soft delete report
# ════════════════════════════════════════════════════════════════════════════
@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def soft_delete_mhc_report(request, investBillNo):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_mhcreport']

    try:
        user_id = request.data.get('auth-user-id', 'system')
        reason = request.data.get('reason', '').strip()

        report = collection.find_one({'investBillNo': investBillNo, 'is_active': True})
        if not report:
            return JsonResponse({'error': 'Report not found'}, status=404)

        collection.update_one(
            {'_id': report['_id']},
            {'$set': {
                'is_active': False,
                'deleted_by': user_id,
                'deleted_date': timezone.now(),
                'deleted_reason': reason,
            }}
        )
        return JsonResponse({'message': 'MHC Report soft-deleted successfully'}, status=200)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    finally:
        client.close()


# ════════════════════════════════════════════════════════════════════════════
#  PATCH  /mhc-reports/slot/<investBillNo>/   → slot management
# ════════════════════════════════════════════════════════════════════════════
@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_mhc_slot(request, investBillNo):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_mhcreport']

    try:
        user_id = request.data.get('auth-user-id', 'system')
        branch_code = request.data.get('auth-branch-code', 'SHB001')
        outlet_code = request.data.get('auth-outlet-code', 'OLET003')
        hospital_code = request.data.get('auth-hospital-code', 'SH001')
        raw_slot = request.data.get('slot_DateTime')

        if not raw_slot:
            return JsonResponse({"error": "slot_DateTime is required"}, status=400)

        slot_dt = _parse_slot_datetime(raw_slot)
        if not slot_dt:
            return JsonResponse({"error": "Invalid slot_DateTime format"}, status=400)

        report = collection.find_one({'investBillNo': investBillNo, 'is_active': True})
        if report:
            collection.update_one(
                {'_id': report['_id']},
                {'$set': {
                    'slot_DateTime': slot_dt,
                    'lastmodified_by': user_id,
                    'lastmodified_date': timezone.now(),
                }}
            )
            updated = collection.find_one({'_id': report['_id']})
            return JsonResponse(_serialize_report(updated), safe=False, status=200)
        else:
            new_doc = {
                'date': timezone.now(),
                'slot_DateTime': slot_dt,
                'investBillNo': investBillNo,
                'uhid': request.data.get('uhid', ''),
                'package_id': request.data.get('package_id', ''),
                'packageName': request.data.get('packageName', ''),
                'billTypeNo': 'PACK',
                'valuedetails': {},
                'impression': '',
                'is_approved': False,
                'has_report': False,
                'is_active': True,
                'created_by': user_id,
                'created_date': timezone.now(),
                'branch_code': branch_code,
                'outlet_code': outlet_code,
                'hospital_code': hospital_code,
            }
            collection.insert_one(new_doc)
            updated = collection.find_one({'investBillNo': investBillNo, 'is_active': True})
            return JsonResponse(_serialize_report(updated), safe=False, status=201)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    finally:
        client.close()


# ════════════════════════════════════════════════════════════════════════════
#  PATCH  /mhc-reports/checkin/<investBillNo>/   → patient check-in
# ════════════════════════════════════════════════════════════════════════════
@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def mhc_patient_checkin(request, investBillNo):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_mhcreport']

    try:
        user_id = request.data.get('auth-user-id', 'system')
        now = timezone.now()

        report = collection.find_one({'investBillNo': investBillNo, 'is_active': True})
        if report:
            collection.update_one(
                {'_id': report['_id']},
                {'$set': {'patientIn_DateTime': now, 'lastmodified_by': user_id, 'lastmodified_date': now}}
            )
            updated = collection.find_one({'_id': report['_id']})
            return JsonResponse(_serialize_report(updated), safe=False, status=200)
        else:
            new_doc = {
                'date': now,
                'investBillNo': investBillNo,
                'uhid': request.data.get('uhid', ''),
                'package_id': request.data.get('package_id', ''),
                'packageName': request.data.get('packageName', ''),
                'billTypeNo': 'PACK',
                'patientIn_DateTime': now,
                'valuedetails': {},
                'impression': '',
                'is_approved': False,
                'has_report': False,
                'is_active': True,
                'created_by': user_id,
                'created_date': now,
                'branch_code': request.data.get('auth-branch-code', 'SHB001'),
                'outlet_code': request.data.get('auth-outlet-code', 'OLET003'),
                'hospital_code': request.data.get('auth-hospital-code', 'SH001'),
            }
            collection.insert_one(new_doc)
            updated = collection.find_one({'investBillNo': investBillNo, 'is_active': True})
            return JsonResponse(_serialize_report(updated), safe=False, status=201)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    finally:
        client.close()


# ════════════════════════════════════════════════════════════════════════════
#  PATCH  /mhc-reports/dispatch/<investBillNo>/   → dispatch report
# ════════════════════════════════════════════════════════════════════════════
@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def mhc_dispatch_report(request, investBillNo):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_mhcreport']

    try:
        user_id = request.data.get('auth-user-id', 'system')
        now = timezone.now()
        report = collection.find_one({'investBillNo': investBillNo, 'is_active': True})
        if not report:
            return JsonResponse({'error': 'Report not found'}, status=404)

        collection.update_one(
            {'_id': report['_id']},
            {'$set': {'dispatch_DateTime': now, 'is_Dispatched': True, 'lastmodified_by': user_id, 'lastmodified_date': now}}
        )
        updated = collection.find_one({'_id': report['_id']})
        return JsonResponse(_serialize_report(updated), safe=False, status=200)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    finally:
        client.close()
