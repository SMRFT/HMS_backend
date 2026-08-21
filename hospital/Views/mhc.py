from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
from datetime import datetime, date, time, timedelta
from django.utils import timezone
from bson import ObjectId
from pathlib import Path
from dotenv import load_dotenv
import pytz
import os
import re
import json
import requests
import logging
from ..models import CommunicationLog, Patient

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
                        'mobilePhone': getattr(p, 'mobilePhone', '') or getattr(p, 'phone', '') or '',
                        'phone': getattr(p, 'phone', '') or getattr(p, 'mobilePhone', '') or '',
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

            # Attach phone/contact details
            phone_val = (
                patient_doc.get('mobilePhone')
                or patient_doc.get('phone')
                or patient_doc.get('mobile')
                or patient_doc.get('phoneNumber')
                or record.get('mobilePhone')
                or record.get('phone')
                or record.get('mobile')
                or ''
            )
            row['phone'] = str(phone_val).strip() if phone_val else ''
            row['mobilePhone'] = str(phone_val).strip() if phone_val else ''

            # Attach review / next due date and check-in flags from report
            if existing_report:
                due_val = existing_report.get('next_due_date') or existing_report.get('next_review_date', '')
                if not due_val and existing_report.get('formattedValuedetails'):
                    f_details = existing_report.get('formattedValuedetails', {})
                    if isinstance(f_details, dict):
                        due_sec = f_details.get('next_master_health_check-up_due')
                        if isinstance(due_sec, list):
                            d_item = next((i for i in due_sec if isinstance(i, dict) and i.get('test_code') == 'NMHCD02'), None)
                            if d_item:
                                due_val = d_item.get('value', '')
                        elif isinstance(due_sec, dict):
                            due_val = due_sec.get('NMHCD02', '')
                row['next_due_date'] = due_val or ''
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


# ════════════════════════════════════════════════════════════════════════════
#  MHC WHATSAPP REMINDERS (TEMPLATE: mhc_reminder)
# ════════════════════════════════════════════════════════════════════════════

def get_mhc_template_name():
    env_path = Path(__file__).resolve().parent.parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path, override=True)
    return (os.getenv("BOTIFY_MHC_TEMPLATE_NAME") or "mhc_reminder_final").strip()


def _normalize_due_date(val):
    """
    Parses various date formats and returns (iso_date_str_YYYY_MM_DD, formatted_display_date_DD_MM_YYYY)
    """
    if not val:
        return None, None
    if isinstance(val, (datetime, date)):
        return val.strftime('%Y-%m-%d'), val.strftime('%d/%m/%Y')
    s = str(val).strip()
    if not s:
        return None, None
    # ISO YYYY-MM-DD
    if re.match(r'^\d{4}-\d{2}-\d{2}', s):
        try:
            d = datetime.strptime(s[:10], '%Y-%m-%d').date()
            return d.strftime('%Y-%m-%d'), d.strftime('%d/%m/%Y')
        except Exception:
            pass
    # DD/MM/YYYY or DD-MM-YYYY
    parts = re.split(r'[/.-]', s)
    if len(parts) == 3:
        try:
            if len(parts[0]) == 4:  # YYYY/MM/DD
                d = date(int(parts[0]), int(parts[1]), int(parts[2]))
            else:  # DD/MM/YYYY
                d = date(int(parts[2]), int(parts[1]), int(parts[0]))
            return d.strftime('%Y-%m-%d'), d.strftime('%d/%m/%Y')
        except Exception:
            pass
    return s[:10], s


def send_whatsapp_mhc_reminder(patient_id, patient_name, phone, next_due_date_str, package_name="", force=False):
    """
    Sends WhatsApp MHC reminder using Botify API template 'mhc_reminder_final'.
    Template variables:
      {{1}} = Patient Name
      {{2}} = Next Due Date
      {{3}} = Patient Name
      {{4}} = Next Due Date
    Logs outcome in CommunicationLog model.
    """
    clean_phone = re.sub(r'\D', '', str(phone or ''))
    if len(clean_phone) == 10:
        clean_phone = f"91{clean_phone}"

    template_name = get_mhc_template_name()
    botify_apikey = (os.getenv("BOTIFY_API_KEY") or "").strip()

    # Formatted due date string (e.g. 20/08/2026)
    _, formatted_due_date = _normalize_due_date(next_due_date_str)
    if not formatted_due_date:
        formatted_due_date = str(next_due_date_str)

    if not clean_phone or len(clean_phone) < 10:
        err_msg = f"Invalid mobile phone number: '{phone}' for patient {patient_name} ({patient_id})"
        logger.warning(err_msg)
        try:
            CommunicationLog.objects.create(
                patient_id=str(patient_id or ''),
                patient_name=str(patient_name or patient_id or ''),
                type="WhatsApp",
                sender=os.getenv("WHATSAPP_SENDER_NUMBER", "WhatsApp API"),
                recipient=str(phone or ''),
                status="Failed",
                details=err_msg,
                template_name=template_name,
                created_by="system",
                branch_code="SHB001",
                hospital_code="SH001"
            )
        except Exception as log_ex:
            logger.error(f"Error logging failed CommunicationLog: {str(log_ex)}")
        return {"success": False, "error": err_msg}

    # One-Time Reminder Check: check if already successfully sent for this patient_id, template_name, and due date
    if not force:
        try:
            # Check CommunicationLog for existing successful reminder for this patient and due date
            already_sent = CommunicationLog.objects.filter(
                patient_id=str(patient_id),
                template_name=template_name,
                status="Success",
                details__icontains=str(formatted_due_date)
            ).exists()

            if not already_sent and next_due_date_str:
                iso_d, _ = _normalize_due_date(next_due_date_str)
                if iso_d:
                    already_sent = CommunicationLog.objects.filter(
                        patient_id=str(patient_id),
                        template_name=template_name,
                        status="Success",
                        details__icontains=str(iso_d)
                    ).exists()

            if already_sent:
                msg = f"MHC reminder already sent previously for patient {patient_name} ({patient_id}) due on {formatted_due_date}"
                logger.info(msg)
                return {"success": True, "skipped": True, "message": msg}
        except Exception as dup_ex:
            logger.warning(f"Duplicate check warning: {str(dup_ex)}")

    if botify_apikey.startswith("Bearer "):
        clean_api_key = botify_apikey[7:].strip()
        auth_header = botify_apikey
    else:
        clean_api_key = botify_apikey
        auth_header = f"Bearer {botify_apikey}"

    botify_url = "https://login.botify.in/api/whatsapp/external"
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json"
    }

    # {{1}} = Patient Name, {{2}} = Next Due Date, {{3}} = Patient Name, {{4}} = Next Due Date
    p_name = str(patient_name or patient_id or "Valued Client").strip()
    template_data = [
        p_name,
        str(formatted_due_date),
        p_name,
        str(formatted_due_date)
    ]

    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "text": str(p)
                } for p in template_data
            ]
        }
    ]

    body_payload = {
        "to": clean_phone,
        "type": "template",
        "templateName": template_name,
        "templateData": template_data,
        "components": components
    }

    try:
        r = requests.post(botify_url, json=body_payload, headers=headers, timeout=20)
        try:
            response_json = r.json()
            is_success = r.status_code in [200, 201] and (
                response_json.get("success") is True or
                response_json.get("status") in [True, "success", "200", 200] or
                response_json.get("result") == "success"
            )
        except ValueError:
            response_json = {}
            is_success = r.status_code in [200, 201]

        # Fallback if single parameter is configured in Botify
        if not is_success and "does not match the expected number of params" in r.text:
            alt_template_data = [str(formatted_due_date)]
            alt_components = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in alt_template_data]
                }
            ]
            alt_payload = {
                "to": clean_phone,
                "type": "template",
                "templateName": template_name,
                "templateData": alt_template_data,
                "components": alt_components
            }
            r_alt = requests.post(botify_url, json=alt_payload, headers=headers, timeout=20)
            try:
                alt_json = r_alt.json()
                if r_alt.status_code in [200, 201] and (
                    alt_json.get("success") is True or
                    alt_json.get("status") in [True, "success", "200", 200] or
                    alt_json.get("result") == "success"
                ):
                    r = r_alt
                    response_json = alt_json
                    is_success = True
            except Exception:
                pass

        status_str = "Success" if is_success else "Failed"
        details_text = f"MHC Reminder for next due date {formatted_due_date} (Pkg: {package_name}). Botify Response: {r.text}"

        CommunicationLog.objects.create(
            patient_id=str(patient_id or ''),
            patient_name=str(patient_name or patient_id or ''),
            type="WhatsApp",
            sender=os.getenv("WHATSAPP_SENDER_NUMBER", "WhatsApp API"),
            recipient=clean_phone,
            status=status_str,
            details=details_text,
            template_name=template_name,
            created_by="system",
            branch_code="SHB001",
            hospital_code="SH001"
        )

        return {"success": is_success, "recipient": clean_phone, "response": response_json, "status_code": r.status_code}

    except Exception as e:
        err_text = f"Exception sending MHC reminder WhatsApp to {clean_phone}: {str(e)}"
        logger.error(err_text)
        try:
            CommunicationLog.objects.create(
                patient_id=str(patient_id or ''),
                patient_name=str(patient_name or patient_id or ''),
                type="WhatsApp",
                sender=os.getenv("WHATSAPP_SENDER_NUMBER", "WhatsApp API"),
                recipient=clean_phone,
                status="Failed",
                details=err_text,
                template_name=template_name,
                created_by="system",
                branch_code="SHB001",
                hospital_code="SH001"
            )
        except Exception:
            pass
        return {"success": False, "error": str(e)}


def process_pending_mhc_reminders(target_date=None, force=False, target_uhid=None):
    """
    Finds active MHC patients where next_due_date is target_date (default: tomorrow, i.e. 1 day before next due date).
    Sends WhatsApp reminders via Botify API with template 'mhc_reminder' and logs in CommunicationLog.
    """
    if not target_date:
        # 1 day before next due date => next due date is tomorrow
        target_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    client = None
    results = {
        "target_date": target_date,
        "total_patients_checked": 0,
        "reminders_sent": 0,
        "reminders_skipped": 0,
        "failed_sends": 0,
        "details": []
    }

    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        mhc_report_coll = db['hospital_mhcreport']
        patient_coll = db['hospital_patient']

        # Find all active MHC reports
        report_query = {"is_active": True}
        if target_uhid:
            report_query["uhid"] = str(target_uhid)

        reports = list(mhc_report_coll.find(report_query))
        
        due_patients = {}  # uhid -> { 'due_date': ..., 'formatted_due_date': ..., 'packageName': ... }

        for rep in reports:
            raw_due = rep.get('next_due_date') or rep.get('next_review_date')
            if not raw_due and rep.get('formattedValuedetails'):
                f_details = rep.get('formattedValuedetails', {})
                if isinstance(f_details, dict):
                    due_sec = f_details.get('next_master_health_check-up_due')
                    if isinstance(due_sec, list):
                        d_item = next((i for i in due_sec if isinstance(i, dict) and i.get('test_code') == 'NMHCD02'), None)
                        if d_item:
                            raw_due = d_item.get('value', '')
                    elif isinstance(due_sec, dict):
                        raw_due = due_sec.get('NMHCD02', '')

            iso_due, disp_due = _normalize_due_date(raw_due)
            if iso_due == target_date:
                u = str(rep.get('uhid', '')).strip()
                if u:
                    due_patients[u] = {
                        'due_date': raw_due,
                        'formatted_due_date': disp_due,
                        'investBillNo': rep.get('investBillNo', ''),
                        'packageName': rep.get('packageName', 'Master Health Check-up')
                    }

        uhid_list = list(due_patients.keys())
        results["total_patients_checked"] = len(uhid_list)

        if uhid_list:
            patients = list(patient_coll.find({"uhid": {"$in": uhid_list}}))
            p_map = {p.get("uhid"): p for p in patients}

            for uhid, info in due_patients.items():
                p_info = p_map.get(uhid, {})
                sal = p_info.get("salutation", "")
                fn = p_info.get("firstName", "")
                ln = p_info.get("lastName", "")
                patient_name = f"{sal} {fn} {ln}".strip() if (fn or ln) else uhid

                phone = p_info.get("mobilePhone") or p_info.get("phone") or p_info.get("mobile") or ""

                res = send_whatsapp_mhc_reminder(
                    patient_id=uhid,
                    patient_name=patient_name,
                    phone=phone,
                    next_due_date_str=info['due_date'],
                    package_name=info['packageName'],
                    force=force
                )

                if res.get("skipped"):
                    results["reminders_skipped"] += 1
                elif res.get("success"):
                    results["reminders_sent"] += 1
                    if info.get('investBillNo'):
                        try:
                            mhc_report_coll.update_many(
                                {"investBillNo": info['investBillNo'], "is_active": True},
                                {"$set": {
                                    "reminder_sent": True,
                                    "reminder_sent_date": datetime.now(),
                                    "reminder_due_date": info['formatted_due_date']
                                }}
                            )
                        except Exception:
                            pass
                else:
                    results["failed_sends"] += 1

                results["details"].append({
                    "uhid": uhid,
                    "patient_name": patient_name,
                    "phone": phone,
                    "next_due_date": info['formatted_due_date'],
                    "status": "Skipped" if res.get("skipped") else ("Success" if res.get("success") else "Failed"),
                    "result": res
                })

        return results

    except Exception as e:
        logger.error(f"Error in process_pending_mhc_reminders: {str(e)}")
        results["error"] = str(e)
        return results
    finally:
        if client:
            client.close()


@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def send_mhc_reminders_api(request):
    """
    Trigger sending MHC reminders for a target date (default: tomorrow, 1 day before due date).
    """
    try:
        target_date = request.data.get('date') or request.GET.get('date')
        force = request.data.get('force', False) or request.GET.get('force') == 'true'
        target_uhid = request.data.get('uhid') or request.GET.get('uhid')

        results = process_pending_mhc_reminders(target_date=target_date, force=force, target_uhid=target_uhid)
        return Response({"success": True, "data": results}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error in send_mhc_reminders_api: {str(e)}")
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def preview_mhc_reminders_api(request):
    """
    Preview pending MHC reminders for a target date (default: tomorrow).
    """
    try:
        target_date = request.GET.get('date')
        if not target_date:
            target_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        mhc_report_coll = db['hospital_mhcreport']
        patient_coll = db['hospital_patient']

        reports = list(mhc_report_coll.find({"is_active": True}))
        preview_list = []

        for rep in reports:
            raw_due = rep.get('next_due_date') or rep.get('next_review_date')
            if not raw_due and rep.get('formattedValuedetails'):
                f_details = rep.get('formattedValuedetails', {})
                if isinstance(f_details, dict):
                    due_sec = f_details.get('next_master_health_check-up_due')
                    if isinstance(due_sec, list):
                        d_item = next((i for i in due_sec if isinstance(i, dict) and i.get('test_code') == 'NMHCD02'), None)
                        if d_item:
                            raw_due = d_item.get('value', '')
                    elif isinstance(due_sec, dict):
                        raw_due = due_sec.get('NMHCD02', '')

            iso_due, disp_due = _normalize_due_date(raw_due)
            if iso_due == target_date:
                u = str(rep.get('uhid', '')).strip()
                p_doc = patient_coll.find_one({"uhid": u}) or {}
                sal = p_doc.get("salutation", "")
                fn = p_doc.get("firstName", "")
                ln = p_doc.get("lastName", "")
                name = f"{sal} {fn} {ln}".strip() if (fn or ln) else u
                phone = p_doc.get("mobilePhone") or p_doc.get("phone") or ""

                already_sent = CommunicationLog.objects.filter(
                    patient_id=u,
                    template_name=get_mhc_template_name(),
                    status="Success",
                    details__icontains=str(disp_due or raw_due)
                ).exists()

                preview_list.append({
                    "uhid": u,
                    "patient_name": name,
                    "phone": phone,
                    "package_name": rep.get('packageName', 'Master Health Check-up'),
                    "investBillNo": rep.get('investBillNo', ''),
                    "next_due_date": disp_due or raw_due,
                    "already_sent": already_sent
                })

        client.close()
        return Response({
            "success": True,
            "target_date": target_date,
            "count": len(preview_list),
            "data": preview_list
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in preview_mhc_reminders_api: {str(e)}")
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

