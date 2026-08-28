from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.shortcuts import render
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
import os, json
import logging
logger = logging.getLogger(__name__)
from ..models import RadiologyReport
from datetime import datetime, timedelta, timezone as dt_timezone
from django.utils import timezone
import gridfs



@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_hard_bill_types(request):
    BILL_TYPES = [
        {"label": "CT",    "value": "CT01"},
        {"label": "MRI",   "value": "MRI01"},
        {"label": "USG",   "value": "USG01"},
        {"label": "X-RAY", "value": "XRAY01"},
    ]
    return JsonResponse(BILL_TYPES, safe=False)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _serialize_report(doc):
    doc["_id"] = str(doc["_id"])
    
    # These all need IST conversion
    for field in [
        "date", "created_date", "lastmodified_date",
        "approved_date", "deleted_date",
        "patientIn_DateTime", "scan_started_DateTime", "dispatch_DateTime",
    ]:
        if field in doc and isinstance(doc[field], datetime):
            doc[field] = _to_ist(doc[field])  # ← was .isoformat(), now _to_ist()

    # slot_DateTime: no timezone conversion, return as plain time string
    if "slot_DateTime" in doc and isinstance(doc["slot_DateTime"], datetime):
        doc["slot_DateTime"] = doc["slot_DateTime"].strftime('%Y-%m-%dT%H:%M:%S')

    return doc


def _parse_slot_datetime(raw):
    """
    Parse slot_DateTime from a string.
    Accepts ISO format (2025-07-01T14:30:00) or 'YYYY-MM-DDTHH:MM:SS'.
    Treats naive datetimes as UTC so the stored value matches what the user typed.
    Returns a timezone-aware datetime (UTC).
    """
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", ""))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


# ─── TAT Helper ───────────────────────────────────────────────────────────────

def _parse_tat_minutes(tat_str):
    """
    Parse TAT_Time string like '2H', '90M', '1.5H' into total minutes.
    Returns None if unparseable.
    """
    if not tat_str:
        return None
    tat_str = str(tat_str).strip().upper()
    import re
    m = re.match(r'^(\d+(?:\.\d+)?)(H|M)$', tat_str)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2)
    return int(value * 60) if unit == 'H' else int(value)


def _calc_tat(patientIn_DateTime, scan_started_DateTime, dispatch_DateTime, tat_minutes, slot_DateTime=None):
    """
    All internal calculations in seconds for sub-minute accuracy.
    Outputs *_seconds fields alongside *_minutes for display flexibility.
    """
    def _make_aware(dt):
        if dt is None:
            return None
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt.replace("Z", ""))
            except ValueError:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt

    def _fmt(seconds):
        seconds = int(abs(seconds))
        h, rem = divmod(seconds, 3600)
        m, s   = divmod(rem, 60)
        if h:
            return f"{h}h {m}m {s}s" if m or s else f"{h}h"
        if m:
            return f"{m}m {s}s" if s else f"{m}m"
        return f"{s}s"

    tat_seconds = tat_minutes * 60 if tat_minutes else None

    base = {
        "tat_minutes":      tat_minutes,
        "tat_seconds":      tat_seconds,
        "elapsed_minutes":  None,
        "elapsed_seconds":  None,
        "waiting_minutes":  None,
        "waiting_seconds":  None,
        "scan_minutes":     None,
        "scan_seconds":     None,
        "overdue_minutes":  None,
        "overdue_seconds":  None,
    }

    # Resolve all datetimes FIRST — before any guard that references them
    t_in       = _make_aware(patientIn_DateTime)
    t_started  = _make_aware(scan_started_DateTime)
    t_dispatch = _make_aware(dispatch_DateTime)
    t_now      = datetime.now(dt_timezone.utc)

    # Slot punctuality (needs t_in already resolved)
    slot_info = None
    if slot_DateTime and patientIn_DateTime:
        t_slot   = _make_aware(slot_DateTime) if isinstance(slot_DateTime, str) else slot_DateTime
        t_in_val = t_in  # already resolved above
        if t_slot and t_in_val:
            diff = int((t_in_val - t_slot).total_seconds())
            if diff <= 0:
                slot_info = {"status": "on_time",  "label": f"Early by {_fmt(abs(diff))}", "diff_seconds": diff}
            else:
                slot_info = {"status": "late",     "label": f"Late by {_fmt(diff)}",       "diff_seconds": diff}
    elif slot_DateTime and not patientIn_DateTime:
        slot_info = {"status": "not_arrived", "label": "Not arrived", "diff_seconds": None}

    if not tat_minutes:
        return {**base, "status": "unknown",  "label": "TAT N/A",            "slot_info": slot_info}
    if t_in is None:
        return {**base, "status": "waiting",  "label": "Awaiting check-in",  "slot_info": slot_info}
    if t_in is None:
        return {**base, "status": "waiting", "label": "Awaiting check-in"}

    # ── Waiting time: patientIn → scan_started ────────────────────────────
    waiting_seconds = None
    if t_started:
        waiting_seconds = int((t_started - t_in).total_seconds())

    # ── TAT clock starts from scan_started if available, else patientIn ───
    t_start = t_started if t_started else t_in
     # ── Slot Punctuality ──────────────────────────────────────────────────────
     # ── Slot Punctuality ──────────────────────────────────────────────────────
    slot_info = None
    if slot_DateTime and patientIn_DateTime:
            t_slot   = _make_aware(slot_DateTime) if isinstance(slot_DateTime, str) else slot_DateTime
            t_in_val = _make_aware(patientIn_DateTime) if isinstance(patientIn_DateTime, str) else patientIn_DateTime
            if t_slot and t_in_val:
                diff = int((t_in_val - t_slot).total_seconds())
                if diff <= 0:
                    slot_info = {
                        "status": "on_time",
                        "label": f"Early by {_fmt(abs(diff))}",
                        "diff_seconds": diff,  # negative = early
                    }
                else:
                    slot_info = {
                        "status": "late",
                        "label": f"Late by {_fmt(diff)}",
                        "diff_seconds": diff,  # positive = late
                    }
    elif slot_DateTime and not patientIn_DateTime:
            slot_info = {"status": "not_arrived", "label": "Not arrived", "diff_seconds": None}

    def _make_result(elapsed_s, scan_s, status, label):
        overdue_s = max(elapsed_s - tat_seconds, 0)
        return {
            "status":          status,
            "label":           label,
            "elapsed_seconds": elapsed_s,
            "elapsed_minutes": round(elapsed_s / 60, 2),
            "waiting_seconds": waiting_seconds,
            "waiting_minutes": round(waiting_seconds / 60, 2) if waiting_seconds is not None else None,
            "scan_seconds":    scan_s,
            "scan_minutes":    round(scan_s / 60, 2) if scan_s is not None else None,
            "tat_seconds":     tat_seconds,
            "tat_minutes":     tat_minutes,
            "overdue_seconds": overdue_s,
            "overdue_minutes": round(overdue_s / 60, 2),
            "slot_info":       slot_info,
        }

    if t_dispatch:
        elapsed_s = int((t_dispatch - t_start).total_seconds())
        overdue_s = elapsed_s - tat_seconds
        if overdue_s > 0:
            label  = f"Done in {_fmt(elapsed_s)} (delayed {_fmt(overdue_s)})"
            status = "completed_late"
        else:
            label  = f"Done in {_fmt(elapsed_s)}"
            status = "completed"
        return _make_result(elapsed_s, elapsed_s, status, label)
    else:
        elapsed_s = int((t_now - t_start).total_seconds())
        overdue_s = elapsed_s - tat_seconds
        if overdue_s > 0:
            label  = f"Overdue by {_fmt(overdue_s)}"
            status = "overdue"
        else:
            label  = f"{_fmt(tat_seconds - elapsed_s)} left"
            status = "on_track"
        return _make_result(elapsed_s, None, status, label)    

IST = dt_timezone(timedelta(hours=5, minutes=30))

def _to_ist(dt):
    """Convert naive UTC datetime or ISO string to IST ISO string."""
    if not dt:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt  # return as-is if unparseable
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)  # treat naive as UTC
        return dt.astimezone(IST).isoformat()
    return dt


# ─── GET investigations ───────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_investigations(request):

    bill_type_no = request.GET.get('billTypeNo')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    invest_bill_no_filter = request.GET.get('investBillNo')

    if not bill_type_no:
        return JsonResponse({'error': 'billTypeNo query parameter is required'}, status=400)

    branch_code   = request.data.get('auth-branch-code',   'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    global_db = client['Global']
    invest_billing_collection    = db['hospital_investbilling']
    ct_report_collection         = db['hospital_radiologyreport']
    patient_collection           = db['hospital_patient']
    invest_price_collection      = db['hospital_investigationprice']
    refund_collection            = db['hospital_investrefund']
    radiology_format_collection  = db['hospital_radiology_formats']
    diagnostics_profile_coll     = global_db['backend_diagnostics_profile']   # ← new

    try:
        # ── 0. Build item_id → itemName map from investigationprice ──────────
        price_doc = invest_price_collection.find_one(
            {'billTypeNo': bill_type_no, 'is_active': True},
            {'_id': 0, 'Items': 1}
        )
        item_name_map = {}
        if price_doc:
            for itm in price_doc.get('Items', []):
                raw_id = itm.get('item_id')
                if raw_id is not None:
                    item_name_map[int(raw_id)] = itm.get('itemName', '')

        # ── 1. Fetch billing records ──────────────────────────────────────────
        billing_filter = {'is_active': True}
        if hospital_code:
            billing_filter['hospital_code'] = hospital_code
        if branch_code:
            billing_filter['branch_code'] = branch_code
        if invest_bill_no_filter:
            billing_filter['investBillNo'] = invest_bill_no_filter

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

        billing_records = list(invest_billing_collection.find(billing_filter, {'_id': 0}))
        if not billing_records:
            return JsonResponse([], safe=False)

        # ── 2. Batch Refund Cache ─────────────────────────────────────────────
        invest_bill_nos = [
            r.get('investBillNo') for r in billing_records if r.get('investBillNo')
        ]

        refunded_test_ids = {}  # investBillNo → set of int test_ids

        if invest_bill_nos:
            refund_docs = refund_collection.find(
                {'investBillNo': {'$in': invest_bill_nos}, 'is_active': True},
                {'_id': 0, 'investBillNo': 1, 'item': 1}
            )
            for rdoc in refund_docs:
                bill_no = rdoc.get('investBillNo')
                items   = rdoc.get('item', [])
                if isinstance(items, str):
                    try:
                        items = json.loads(items)
                    except:
                        items = []
                if bill_no not in refunded_test_ids:
                    refunded_test_ids[bill_no] = set()
                for it in items:
                    tid = it.get('item_id') or it.get('test_id')
                    if tid is not None:
                        try:
                            refunded_test_ids[bill_no].add(int(tid))
                        except (ValueError, TypeError):
                            refunded_test_ids[bill_no].add(tid)

        # ── 3. Filter by billTypeNo and exclude refunded items ────────────────
        filtered_records = []
        for record in billing_records:
            try:
                items = record.get('item', [])
                if isinstance(items, str):
                    try:
                        items = json.loads(items)
                    except:
                        items = []
            except:
                items = []

            bill_no          = record.get('investBillNo', '')
            already_refunded = refunded_test_ids.get(bill_no, set())

            matched_items = []
            for i in items:
                if i.get('billTypeNo') != bill_type_no:
                    continue
                tid = i.get('item_id') or i.get('test_id')
                try:
                    tid_norm = int(tid) if tid is not None else None
                except (ValueError, TypeError):
                    tid_norm = tid
                if tid_norm in already_refunded:
                    continue
                matched_items.append(i)

            if not matched_items:
                continue

            record['_matched_items'] = matched_items
            filtered_records.append(record)

        if not filtered_records:
            return JsonResponse([], safe=False)

        # ── 4. Fetch existing reports ─────────────────────────────────────────
        bill_nos = [r['investBillNo'] for r in filtered_records if r.get('investBillNo')]
        report_filter = {
            'investBillNo': {'$in': bill_nos},
            'is_active': True
        }
        if hospital_code:
            report_filter['hospital_code'] = hospital_code
        if branch_code:
            report_filter['branch_code'] = branch_code

        ct_reports = list(ct_report_collection.find(report_filter, {'_id': 0}))

        report_map = {}
        for r in ct_reports:
            for field in ['date', 'created_date', 'lastmodified_date',
                          'approved_date', 'deleted_date',
                          'patientIn_DateTime', 'scan_started_DateTime', 'dispatch_DateTime']:
                if field in r:
                    r[field] = _to_ist(r[field])

            # slot_DateTime: return raw UTC ISO string, no timezone shift
            if 'slot_DateTime' in r and isinstance(r['slot_DateTime'], datetime):
                r['slot_DateTime'] = r['slot_DateTime'].strftime('%Y-%m-%dT%H:%M:%S')

            raw_item_id        = r.get('item_id')
            normalized_item_id = int(raw_item_id) if raw_item_id is not None else None
            report_map[(r.get('investBillNo'), normalized_item_id)] = r

        # ── 5. Fetch patients ─────────────────────────────────────────────────
        uhid_list = list({r['uhid'] for r in filtered_records if r.get('uhid', '').strip()})
        patient_filter = {'uhid': {'$in': uhid_list}}
        if hospital_code:
            patient_filter['hospital_code'] = hospital_code
        if branch_code:
            patient_filter['branch_code'] = branch_code

        patients = list(patient_collection.find(
            patient_filter,
            {'_id': 0, 'uhid': 1, 'salutation': 1, 'firstName': 1, 'middleName': 1,
             'lastName': 1, 'gender': 1, 'address': 1, 'address1': 1, 'address2': 1,
             'city': 1, 'area': 1, 'pincode': 1, 'state': 1, 'door_no': 1, 'street': 1,
             'mobilePhone': 1, 'mobile_number': 1, 'customer_type': 1, 'customerType': 1,
             'company_code': 1}
        ))
        patient_map = {p['uhid']: p for p in patients}

        # ── 5a. Insurance Providers Cache ─────────────────────────────────────
        company_codes = list({str(p.get('company_code')).strip() for p in patients if p.get('company_code') and str(p.get('company_code')).strip()})
        insurance_map = {}
        if company_codes:
            insurance_provider_coll = db['hospital_insuranceprovider']
            for ip in insurance_provider_coll.find({'company_code': {'$in': company_codes}}, {'_id': 0, 'company_code': 1, 'company_name': 1}):
                if ip.get('company_code'):
                    insurance_map[str(ip['company_code'])] = ip.get('company_name', '')

        # ── 5b. Doctor / ReferredBy Cache ─────────────────────────────────────
        doctor_ids      = set()
        referred_by_ids = set()

        for record in filtered_records:
            doc_val = record.get('doctor', '')
            ref_val = record.get('referredBy', '')

            if doc_val and str(doc_val).upper() != 'SELF':
                doctor_ids.add(str(doc_val))
            if ref_val and str(ref_val).upper() != 'SELF':
                referred_by_ids.add(str(ref_val))

        diagnostics_profile_cache = {}  # employeeId → employeeName

        all_profile_ids = doctor_ids | referred_by_ids
        if all_profile_ids:
            profile_docs = diagnostics_profile_coll.find(
                {'employeeId': {'$in': list(all_profile_ids)}},
                {'_id': 0, 'employeeId': 1, 'employeeName': 1}
            )
            for p in profile_docs:
                emp_id = str(p.get('employeeId', ''))
                if emp_id:
                    diagnostics_profile_cache[emp_id] = p.get('employeeName', '')

        # ── 6. Batch Radiology Format Cache ──────────────────────────────────
        all_item_ids = set()
        for record in filtered_records:
            for item in record.get('_matched_items', []):
                tid = item.get('test_id') or item.get('item_id')
                if tid is not None:
                    try:
                        all_item_ids.add(int(tid))
                    except (ValueError, TypeError):
                        pass

        format_map = {}
        if all_item_ids:
            format_docs = radiology_format_collection.find(
                {
                    'item_id':    {'$in': list(all_item_ids)},
                    'billTypeNo': bill_type_no,
                    'is_active':  True
                }
            )
            for fdoc in format_docs:
                fdoc.pop('_id', None)
                for field in ['last_modified_date']:
                    if field in fdoc and isinstance(fdoc[field], datetime):
                        fdoc[field] = fdoc[field].isoformat()
                fid = fdoc.get('item_id')
                if fid is not None:
                    try:
                        format_map[int(fid)] = fdoc
                    except (ValueError, TypeError):
                        pass

        # ── 7. Build result ───────────────────────────────────────────────────
        result = []
        for record in filtered_records:
            invest_bill_no = record.get('investBillNo')
            if not invest_bill_no:
                continue

            uhid    = record.get('uhid', '').strip()
            patient = patient_map.get(uhid, {}) if uhid else {}

            # ── Patient info: prefer patient_cache, fall back to billing doc ──
            salutation  = patient.get('salutation',  '') or record.get('salutation',  '')
            first_name  = patient.get('firstName',   '') or record.get('firstName',   '')
            middle_name = patient.get('middleName',  '') or record.get('middleName',  '')
            last_name   = patient.get('lastName',    '') or record.get('lastName',    '')
            gender      = patient.get('gender',      '') or record.get('gender',      '')

            gender_clean = gender.strip().upper()
            if gender_clean in ('M', 'MALE'):
                gender_key = 'male'
            elif gender_clean in ('F', 'FEMALE'):
                gender_key = 'female'
            else:
                gender_key = 'male'

            matched_items = record.get('_matched_items', [])

            base = record.copy()
            base.pop('_matched_items', None)
            base.pop('item', None)

            for field in ['investBillDate', 'created_date', 'lastmodified_date']:
                if field in base:
                    base[field] = _to_ist(base[field])

            base['salutation']  = salutation
            base['firstName']   = first_name
            base['middleName']  = middle_name
            base['lastName']    = last_name
            base['gender']      = gender

            # Address resolution
            addr_parts = [
                patient.get('door_no'),
                patient.get('street') or patient.get('address1') or patient.get('address'),
                patient.get('address2') or patient.get('area'),
                patient.get('city'),
                patient.get('state'),
                patient.get('pincode')
            ]
            full_addr = ', '.join([str(p).strip() for p in addr_parts if p and str(p).strip()])
            base['address'] = full_addr or record.get('address', '') or record.get('patientAddress', '') or ''
            base['patientType'] = 'IP' if record.get('ipNumber') else (record.get('patientType') or record.get('customerType') or 'OP')

            # Customer Type & Insurance Company
            cust_type = patient.get('customer_type') or patient.get('customerType') or record.get('customer_type') or record.get('customerType') or 'General'
            comp_code = str(patient.get('company_code') or record.get('company_code') or '').strip()
            comp_name = insurance_map.get(comp_code, '') or patient.get('insurance_company') or record.get('insurance_company') or (comp_code if comp_code else '')

            base['customer_type']     = cust_type
            base['customerType']      = cust_type
            base['company_code']      = comp_code
            base['company_name']      = comp_name
            base['insurance_company'] = comp_name

            # ── Doctor name ───────────────────────────────────────────────────
            doc_val = record.get('doctor', '')
            if doc_val and str(doc_val).upper() == 'SELF':
                base['doctorName'] = 'SELF'
            else:
                base['doctorName'] = diagnostics_profile_cache.get(str(doc_val), '')

            # ── ReferredBy name ───────────────────────────────────────────────
            ref_val = record.get('referredBy', '')
            if ref_val and str(ref_val).upper() == 'SELF':
                base['referredByName'] = 'SELF'
            else:
                base['referredByName'] = diagnostics_profile_cache.get(str(ref_val), '')

            for item in matched_items:
                raw_item_id = item.get('item_id') or item.get('test_id')
                item_id     = int(raw_item_id) if raw_item_id is not None else None

                item_name = item_name_map.get(item_id) or item.get('itemName', '')
                report    = report_map.get((invest_bill_no, item_id))

                row = base.copy()
                row['item_id']   = item_id
                row['itemName']  = item_name
                row['report']    = report
                row['hasReport'] = report.get('has_report', False) if report else False

                fmt_doc = format_map.get(item_id)
                if fmt_doc:
                    fmt_base = {
                        k: v for k, v in fmt_doc.items()
                        if k not in ('male', 'female')
                    }
                    fmt_base['format_titles'] = fmt_doc.get(gender_key, [])
                    row['radiology_format'] = fmt_base

                    tat_minutes  = _parse_tat_minutes(fmt_doc.get('TAT_Time')) if fmt_doc else None
                    patient_in   = report.get('patientIn_DateTime')   if report else None
                    scan_started = report.get('scan_started_DateTime') if report else None
                    dispatch_dt  = report.get('dispatch_DateTime')     if report else None
                    slot_dt_raw  = report.get('slot_DateTime')         if report else None
                    row['tat_info']  = _calc_tat(patient_in, scan_started, dispatch_dt, tat_minutes, slot_DateTime=slot_dt_raw)
                    row['scan_type'] = (fmt_doc.get('type') or '').upper() if fmt_doc else ''
                else:
                    row['radiology_format'] = None

                result.append(row)

        return JsonResponse(result, safe=False)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

    finally:
        client.close()
# ─── POST: Create scan report (with optional slot_DateTime) ───────────────────

@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_scan_report(request):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        data          = request.data
        user_id       = data.get('auth-user-id', 'system')
        branch_code   = data.get('auth-branch-code', 'SHB001')
        outlet_code   = data.get('auth-outlet-code', 'OLET003')
        hospital_code = data.get('auth-hospital-code', 'SH001')
        invest_bill_no = data.get('investBillNo')

        try:
            item_id = int(data.get('item_id'))
        except (ValueError, TypeError):
            return JsonResponse({"error": "item_id must be a valid integer"}, status=400)

        # ── Parse dates ──────────────────────────────────────────────────────
        invest_bill_date = data.get('investBillDate')
        if invest_bill_date:
            try:
                date_value = datetime.fromisoformat(invest_bill_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                date_value = timezone.now()
        else:
            date_value = timezone.now()

        slot_dt = _parse_slot_datetime(data.get('slot_DateTime'))

        # ── Build valuedetails ───────────────────────────────────────────────
        sections = data.get('sections', [])
        value_list = []

        for sec in sections:
            if sec.get('table_id'):
                # Table entry — store as-is (has table_id + title_id + row values)
                value_list.append(sec)
            else:
                # Text entry — store only title_id and title_value, no title
                value_list.append({
                    "title_id":    sec.get('title_id', ''),
                    "title_value": sec.get('title_value', ''),
                })

        anc_fields = data.get('anc_fields', None)

        valuedetails = {
            "device_id":    data.get('device_id', []),
            "value":        value_list,
            **({"anc_fields": anc_fields} if anc_fields else {}),
        }

        impression    = data.get('impression', '')
        item_name     = data.get('itemName', '')
        bill_type_no  = data.get('billTypeNo', '')

        # ── Check if a patchable record exists ───────────────────────────────
        existing_slot = collection.find_one({
            'investBillNo': invest_bill_no,
            'item_id':      item_id,
            'is_active':    True,
            'is_approved':  {'$ne': True},
            '$or': [
                {'has_report': False},
                {'impression': ''},
                {'impression': None},
            ]
        })

        if existing_slot:
            set_payload = {
                "impression":        impression,
                "valuedetails":      valuedetails,
                "has_report":        True,
                "lastmodified_by":   user_id,
                "lastmodified_date": timezone.now(),
                "type":              data.get('type', ''),
            }
            if slot_dt:
                set_payload["slot_DateTime"] = slot_dt
            if item_name:
                set_payload["itemName"] = item_name
            if bill_type_no:
                set_payload["billTypeNo"] = bill_type_no

            collection.update_one(
                {"_id": existing_slot["_id"]},
                {"$set": set_payload}
            )
            updated = collection.find_one({"_id": existing_slot["_id"]})
            return JsonResponse({
                "id":           str(existing_slot["_id"]),
                "investBillNo": invest_bill_no,
                "message":      "Report updated on existing slot record",
                "report":       _serialize_report(updated),
            }, status=200)

        # ── Duplicate check: a real report already exists ────────────────────
        existing_full = collection.find_one({
            'investBillNo': invest_bill_no,
            'item_id':      item_id,
            'is_active':    True,
            'has_report':   True,
            'impression':   {'$nin': ['', None]},
        })
        if existing_full:
            return JsonResponse(
                {'error': f'A report already exists for Bill No {invest_bill_no}'},
                status=409
            )

        # ── POST: create new record ───────────────────────────────────────────
        has_report = bool(impression and impression.strip())
        report_type = data.get('type', '')

        ct_report = RadiologyReport.objects.create(
            date          = date_value,
            slot_DateTime = slot_dt,
            investBillNo  = invest_bill_no,
            itemName      = item_name,
            item_id       = item_id,
            impression    = impression,
            billTypeNo    = bill_type_no,
            valuedetails  = valuedetails,
            is_active     = True,
            has_report    = has_report,
            type          = report_type,
            created_by    = user_id,
            branch_code   = branch_code,
            outlet_code   = outlet_code,
            hospital_code = hospital_code,
        )

        return JsonResponse({
            "id":           str(ct_report.id),
            "investBillNo": ct_report.investBillNo,
            "message":      "Report created successfully",
        }, status=201)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=400)
    finally:
        client.close()


# ─── PATCH: Update slot_DateTime (and optionally impression) ──────────────────

@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_slot_datetime(request, investBillNo, item_id):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        user_id       = request.data.get('auth-user-id', 'system')
        branch_code   = request.data.get('auth-branch-code', 'SHB001')
        outlet_code   = request.data.get('auth-outlet-code', 'OLET003')
        hospital_code = request.data.get('auth-hospital-code', 'SH001')
        raw_slot      = request.data.get('slot_DateTime')

        if not raw_slot:
            return JsonResponse({"error": "slot_DateTime is required"}, status=400)

        slot_dt = _parse_slot_datetime(raw_slot)
        if not slot_dt:
            return JsonResponse({"error": "Invalid slot_DateTime format."}, status=400)

        try:
            item_id_int = int(item_id)
        except (ValueError, TypeError):
            return JsonResponse({"error": "item_id must be a valid integer"}, status=400)

        report = collection.find_one({
            'investBillNo': investBillNo,
            'item_id':      item_id_int,
            'is_active':    True,
            'has_report':   False,
        })

        if report:
            update_fields = {
                "slot_DateTime":     slot_dt,
                "lastmodified_by":   user_id,
                "lastmodified_date": timezone.now(),
            }
            new_impression = request.data.get('impression')
            if new_impression:
                update_fields["impression"] = new_impression

            collection.update_one({"_id": report["_id"]}, {"$set": update_fields})
            updated = collection.find_one({"_id": report["_id"]})
            return JsonResponse(_serialize_report(updated), safe=False, status=200)

        else:
            invest_bill_date = request.data.get('investBillDate')
            if invest_bill_date:
                try:
                    date_value = datetime.fromisoformat(invest_bill_date.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    date_value = timezone.now()
            else:
                date_value = timezone.now()

            ct_report = RadiologyReport.objects.create(
                date          = date_value,
                slot_DateTime = slot_dt,
                investBillNo  = investBillNo,
                itemName      = request.data.get('itemName', ''),
                item_id       = item_id_int,
                impression    = request.data.get('impression', ''),
                billTypeNo    = request.data.get('billTypeNo', ''),
                valuedetails  = {"device_id": [], "approve": False, "approve_time": None, "approve_by": None, "value": []},
                is_active     = True,
                has_report    = False,
                created_by    = user_id,
                branch_code   = branch_code,
                outlet_code   = outlet_code,
                hospital_code = hospital_code,
            )
            updated = collection.find_one({"investBillNo": investBillNo, "item_id": item_id_int, "is_active": True})
            return JsonResponse(_serialize_report(updated), safe=False, status=201)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()


# ─── PATCH: Approve ───────────────────────────────────────────────────────────

@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def approve_scan_report(request, investBillNo, item_id):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        user_id = request.data.get('auth-user-id', 'system')
        item_id = int(item_id)
        report = collection.find_one(
            {'investBillNo': investBillNo, 'item_id': item_id, 'is_active': True}
        )
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        collection.update_one(
            {"_id": report["_id"]},
            {"$set": {"is_approved": True, "approved_by": user_id, "approved_date": timezone.now()}}
        )
        updated = collection.find_one({"_id": report["_id"]})
        return JsonResponse(_serialize_report(updated), safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()


# ─── PATCH: Edit impression ───────────────────────────────────────────────────

@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def edit_scan_report_impression(request, investBillNo, item_id):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        new_impression = request.data.get("impression")
        new_sections   = request.data.get("sections")
        new_anc_fields = request.data.get("anc_fields", None)
        user_id        = request.data.get('auth-user-id', 'system')
        item_id        = int(item_id)

        if not new_impression and not new_sections:
            return JsonResponse(
                {"error": "At least one of 'impression' or 'sections' is required"},
                status=400
            )

        report = collection.find_one(
            {'investBillNo': investBillNo, 'item_id': item_id, 'is_active': True}
        )
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        set_payload = {
            "lastmodified_by":   user_id,
            "lastmodified_date": timezone.now(),
        }

        if new_impression:
            set_payload["impression"] = new_impression

        if new_sections and isinstance(new_sections, list):
            existing_value = report.get("valuedetails", {}).get("value", [])

            existing_text_map = {
                item["title_id"]: idx
                for idx, item in enumerate(existing_value)
                if item.get("title_id") and not item.get("table_id")
            }

            existing_table_map = {
                item["table_id"]: idx
                for idx, item in enumerate(existing_value)
                if item.get("table_id")
            }

            for incoming in new_sections:
                if incoming.get("table_id"):
                    table_id = incoming["table_id"]
                    if table_id in existing_table_map:
                        existing_value[existing_table_map[table_id]] = incoming
                    else:
                        existing_value.append(incoming)
                else:
                    title_id = incoming.get("title_id")
                    new_val  = incoming.get("title_value")
                    if not title_id or new_val is None:
                        continue
                    if title_id in existing_text_map:
                        idx = existing_text_map[title_id]
                        existing_value[idx]["title_value"] = new_val
                    else:
                        existing_value.append({
                            "title_id":    title_id,
                            "title_value": new_val,
                        })

            set_payload["valuedetails.value"] = existing_value

        if new_anc_fields:
            set_payload["valuedetails.anc_fields"] = new_anc_fields

        collection.update_one(
            {"_id": report["_id"]},
            {"$set": set_payload}
        )

        updated = collection.find_one({"_id": report["_id"]})
        return JsonResponse(_serialize_report(updated), safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()


# ─── PATCH: Soft delete ───────────────────────────────────────────────────────

@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def soft_delete_scan_report(request, investBillNo, item_id):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        user_id = request.data.get('auth-user-id', 'system')
        item_id = int(item_id)
        report = collection.find_one(
            {'investBillNo': investBillNo, 'item_id': item_id, 'is_active': True}
        )
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        collection.update_one(
            {"_id": report["_id"]},
            {"$set": {"is_active": False, "deleted_by": user_id, "deleted_date": timezone.now()}}
        )
        return JsonResponse({"message": "Report deleted successfully"}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()


@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def get_radiology_format(request):
    """
    GET /scan-reports/format/
    Query params:
        - billTypeNo  (required)
        - test_id     (required)
        - gender      (required: 'Male' or 'Female')
    Returns gender-specific fields + common fields from hospital_radiology_formats.
    """

    bill_type_no = request.GET.get('billTypeNo')
    test_id      = request.GET.get('test_id')
    gender       = request.GET.get('gender', '').strip().lower()

    if not bill_type_no:
        return JsonResponse({'error': 'billTypeNo is required'}, status=400)
    if not test_id:
        return JsonResponse({'error': 'test_id is required'}, status=400)
    if gender not in ('male', 'female'):
        return JsonResponse(
            {'error': "gender must be 'Male' or 'Female'"},
            status=400
        )

    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db     = client['HMS']
    collection = db['hospital_radiology_formats']

    try:
        try:
            test_id_query = int(test_id)
        except (ValueError, TypeError):
            test_id_query = test_id

        doc = collection.find_one(
            {
                'billTypeNo': bill_type_no,
                'item_id':    test_id_query,
                'is_active':  True,
            },
            {'_id': 0}
        )

        if not doc:
            return JsonResponse(
                {'error': 'No active format found for given billTypeNo and test_id'},
                status=404
            )

        gender_fields = doc.get(gender, [])

        GENDER_KEYS   = {'male', 'female'}
        EXCLUDED_KEYS = {'last_modified_by', 'last_modified_date'}

        common_fields = {
            k: v
            for k, v in doc.items()
            if k not in GENDER_KEYS and k not in EXCLUDED_KEYS
        }

        for key, value in common_fields.items():
            if isinstance(value, datetime):
                common_fields[key] = value.isoformat()

        response_data = {
            **common_fields,
            'format': gender_fields,
        }

        return JsonResponse(response_data, safe=False)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    finally:
        client.close()


@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def get_employee_signature_by_id(request):
    employee_id = request.GET.get('employee_id')
    if not employee_id:
        return JsonResponse({'error': 'employee_id is required'}, status=400)

    try:
        mongo_client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        global_db = mongo_client.Global

        profile_collection     = global_db.backend_diagnostics_profile
        designation_collection = global_db.backend_diagnostics_Designation
        fs = gridfs.GridFS(global_db)

        profile = profile_collection.find_one({"employeeId": str(employee_id)})
        if not profile:
            return JsonResponse({'error': 'Employee not found'}, status=404)

        employee_name        = profile.get("employeeName", "")
        registration_number  = profile.get("registrationNumber", "")
        designation_code     = profile.get("designation", "")

        designation_name = ""
        if designation_code:
            desig_doc = designation_collection.find_one({"Designation_code": designation_code})
            if desig_doc:
                designation_name = desig_doc.get("designation", "")

        signature_base64  = None
        signature_file_id = profile.get("signatureFileId")
        if signature_file_id:
            try:
                from bson import ObjectId
                import base64
                if isinstance(signature_file_id, str):
                    signature_file_id = ObjectId(signature_file_id)
                signature_file  = fs.get(signature_file_id)
                signature_bytes = signature_file.read()
                signature_base64 = base64.b64encode(signature_bytes).decode('utf-8')
            except Exception as e:
                print(f"Error fetching signature: {str(e)}")

        return JsonResponse({
            "employeeId":         employee_id,
            "employeeName":       employee_name,
            "designation":        designation_name,
            "registrationNumber": registration_number,
            "signatureBase64":    signature_base64,
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


# ─── PATCH: Patient Check-In ──────────────────────────────────────────────────
@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def patient_checkin(request, investBillNo, item_id):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    radiology_format_collection = client['HMS']['hospital_radiology_formats']
    try:
        user_id       = request.data.get('auth-user-id', 'system')
        branch_code   = request.data.get('auth-branch-code', 'SHB001')
        outlet_code   = request.data.get('auth-outlet-code', 'OLET003')
        hospital_code = request.data.get('auth-hospital-code', 'SH001')

        try:
            item_id_int = int(item_id)
        except (ValueError, TypeError):
            return JsonResponse({"error": "item_id must be a valid integer"}, status=400)

        raw_dt = request.data.get('patientIn_DateTime')
        if raw_dt is not None:
            patient_in_dt = _parse_slot_datetime(raw_dt)
            if not patient_in_dt:
                return JsonResponse({"error": "Invalid patientIn_DateTime format."}, status=400)
        else:
            patient_in_dt = None

        report = collection.find_one({
            'investBillNo': investBillNo,
            'item_id':      item_id_int,
            'is_active':    True,
        })

        def _build_response(doc, status_code):
            serialized = _serialize_report(doc)
            fmt_doc = radiology_format_collection.find_one(
                {
                    'item_id':    item_id_int,
                    'billTypeNo': doc.get('billTypeNo'),
                    'is_active':  True,
                },
                {'TAT_Time': 1, '_id': 0}
            )
            tat_minutes  = _parse_tat_minutes(fmt_doc.get('TAT_Time')) if fmt_doc else None
            patient_in   = serialized.get('patientIn_DateTime')
            scan_started = serialized.get('scan_started_DateTime')
            dispatch_str = serialized.get('dispatch_DateTime')
            slot_dt_raw  = serialized.get('slot_DateTime')
            serialized['tat_info'] = _calc_tat(
                patient_in, scan_started, dispatch_str, tat_minutes,
                slot_DateTime=slot_dt_raw
            )
            return JsonResponse(serialized, safe=False, status=status_code)

        if report:
            set_payload = {
                "patientIn_DateTime": patient_in_dt,
                "lastmodified_by":    user_id,
                "lastmodified_date":  timezone.now(),
            }
            collection.update_one({"_id": report["_id"]}, {"$set": set_payload})
            updated = collection.find_one({"_id": report["_id"]})
            return _build_response(updated, 200)

        else:
            invest_bill_date = request.data.get('investBillDate')
            try:
                date_value = datetime.fromisoformat(
                    invest_bill_date.replace("Z", "+00:00")
                ) if invest_bill_date else timezone.now()
            except (ValueError, AttributeError):
                date_value = timezone.now()

            ct_report = RadiologyReport.objects.create(
                date               = date_value,
                slot_DateTime      = None,
                investBillNo       = investBillNo,
                itemName           = request.data.get('itemName', ''),
                item_id            = item_id_int,
                impression         = '',
                billTypeNo         = request.data.get('billTypeNo', ''),
                valuedetails       = {"device_id": [], "value": []},
                is_active          = True,
                has_report         = False,
                patientIn_DateTime = patient_in_dt,
                created_by         = user_id,
                branch_code        = branch_code,
                outlet_code        = outlet_code,
                hospital_code      = hospital_code,
            )
            updated = collection.find_one({
                'investBillNo': investBillNo,
                'item_id':      item_id_int,
                'is_active':    True,
            })
            return _build_response(updated, 201)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()


@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def scan_started(request, investBillNo, item_id):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    radiology_format_collection = client['HMS']['hospital_radiology_formats']
    try:
        user_id       = request.data.get('auth-user-id', 'system')
        branch_code   = request.data.get('auth-branch-code', 'SHB001')
        outlet_code   = request.data.get('auth-outlet-code', 'OLET003')
        hospital_code = request.data.get('auth-hospital-code', 'SH001')

        try:
            item_id_int = int(item_id)
        except (ValueError, TypeError):
            return JsonResponse({"error": "item_id must be a valid integer"}, status=400)

        raw_dt = request.data.get('scan_started_DateTime')
        if raw_dt is not None:
            scan_dt = _parse_slot_datetime(raw_dt)
            if not scan_dt:
                return JsonResponse({"error": "Invalid scan_started_DateTime format."}, status=400)
        else:
            scan_dt = None

        report = collection.find_one({
            'investBillNo': investBillNo,
            'item_id':      item_id_int,
            'is_active':    True,
        })

        def _build_response(doc, status_code):
            serialized = _serialize_report(doc)
            fmt_doc = radiology_format_collection.find_one(
                {
                    'item_id':    item_id_int,
                    'billTypeNo': doc.get('billTypeNo'),
                    'is_active':  True,
                },
                {'TAT_Time': 1, '_id': 0}
            )
            tat_minutes  = _parse_tat_minutes(fmt_doc.get('TAT_Time')) if fmt_doc else None
            patient_in   = serialized.get('patientIn_DateTime')
            scan_started = serialized.get('scan_started_DateTime')
            dispatch_str = serialized.get('dispatch_DateTime')
            slot_dt_raw  = serialized.get('slot_DateTime')
            serialized['tat_info'] = _calc_tat(
                patient_in, scan_started, dispatch_str, tat_minutes,
                slot_DateTime=slot_dt_raw
            )
            return JsonResponse(serialized, safe=False, status=status_code)

        if report:
            set_payload = {
                "scan_started_DateTime": scan_dt,
                "lastmodified_by":       user_id,
                "lastmodified_date":     timezone.now(),
            }
            collection.update_one({"_id": report["_id"]}, {"$set": set_payload})
            updated = collection.find_one({"_id": report["_id"]})
            return _build_response(updated, 200)

        else:
            invest_bill_date = request.data.get('investBillDate')
            try:
                date_value = datetime.fromisoformat(
                    invest_bill_date.replace("Z", "+00:00")
                ) if invest_bill_date else timezone.now()
            except (ValueError, AttributeError):
                date_value = timezone.now()

            ct_report = RadiologyReport.objects.create(
                date                  = date_value,
                slot_DateTime         = None,
                investBillNo          = investBillNo,
                itemName              = request.data.get('itemName', ''),
                item_id               = item_id_int,
                impression            = '',
                billTypeNo            = request.data.get('billTypeNo', ''),
                valuedetails          = {"device_id": [], "value": []},
                is_active             = True,
                has_report            = False,
                scan_started_DateTime = scan_dt,
                created_by            = user_id,
                branch_code           = branch_code,
                outlet_code           = outlet_code,
                hospital_code         = hospital_code,
            )
            updated = collection.find_one({
                'investBillNo': investBillNo,
                'item_id':      item_id_int,
                'is_active':    True,
            })
            return _build_response(updated, 201)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()

# ─── PATCH: Dispatch ──────────────────────────────────────────────────────────

@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def dispatch_report(request, investBillNo, item_id):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    radiology_format_collection = client['HMS']['hospital_radiology_formats']
    try:
        user_id = request.data.get('auth-user-id', 'system')

        try:
            item_id_int = int(item_id)
        except (ValueError, TypeError):
            return JsonResponse({"error": "item_id must be a valid integer"}, status=400)

        report = collection.find_one({
            'investBillNo': investBillNo,
            'item_id':      item_id_int,
            'is_active':    True,
        })
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        if not report.get('is_approved'):
            return JsonResponse({"error": "Only approved reports can be dispatched."}, status=400)

        if report.get('is_Dispatched'):
            return JsonResponse({"error": "Report is already dispatched."}, status=409)

        raw_dt      = request.data.get('dispatch_DateTime')
        dispatch_dt = _parse_slot_datetime(raw_dt) if raw_dt else timezone.now()

        collection.update_one(
            {"_id": report["_id"]},
            {"$set": {
                "is_Dispatched":     True,
                "dispatch_DateTime": dispatch_dt,
                "dispatched_by":     user_id,
                "lastmodified_by":   user_id,
                "lastmodified_date": timezone.now(),
            }}
        )
        updated = collection.find_one({"_id": report["_id"]})
        serialized = _serialize_report(updated)

        # ── Calculate TAT and include in response ────────────────────────────
        fmt_doc = radiology_format_collection.find_one(
            {'item_id': item_id_int, 'billTypeNo': updated.get('billTypeNo'), 'is_active': True},
            {'TAT_Time': 1, '_id': 0}
        )
        tat_minutes  = _parse_tat_minutes(fmt_doc.get('TAT_Time')) if fmt_doc else None
        patient_in   = serialized.get('patientIn_DateTime')
        scan_started = serialized.get('scan_started_DateTime')
        dispatch_str = serialized.get('dispatch_DateTime')
        serialized['tat_info'] = _calc_tat(patient_in, scan_started, dispatch_str, tat_minutes)

        return JsonResponse(serialized, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()


# ─── DICOM & Orthanc Integration ─────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_dicom_study_url(request):
    """
    Queries Orthanc PACS server to locate DICOM studies specifically for a given investBillNo (Accession Number).
    Returns the OHIF Viewer URL without exposing Orthanc credentials to the frontend.
    """
    import urllib.request
    import urllib.parse
    import base64

    invest_bill_no = request.GET.get('investBillNo', '').strip()

    if not invest_bill_no:
        return JsonResponse({'success': False, 'error': 'investBillNo is required.'}, status=400)

    orthanc_url  = (os.getenv('ORTHANC_URL') or '').strip().rstrip('/')
    orthanc_user = (os.getenv('ORTHANC_USERNAME') or '').strip()
    orthanc_pass = (os.getenv('ORTHANC_PASSWORD') or '').strip()
    ohif_url     = (os.getenv('OHIF_VIEWER_URL') or '').strip().rstrip('/')

    if not orthanc_url or not ohif_url:
        return JsonResponse({
            'success': False,
            'error': 'ORTHANC_URL or OHIF_VIEWER_URL is not configured in .env'
        }, status=500)

    find_url = f"{orthanc_url}/tools/find"

    # Query Orthanc /tools/find by PatientID (where bill no is stored in DICOM), fallback to AccessionNumber
    queries_to_try = [
        {"Level": "Study", "Query": {"PatientID": invest_bill_no}},
        {"Level": "Study", "Query": {"AccessionNumber": invest_bill_no}},
    ]

    study_ids = []
    for payload in queries_to_try:
        try:
            req = urllib.request.Request(
                find_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            if orthanc_user and orthanc_pass:
                auth_header = base64.b64encode(f"{orthanc_user}:{orthanc_pass}".encode()).decode()
                req.add_header('Authorization', f"Basic {auth_header}")

            with urllib.request.urlopen(req, timeout=5) as response:
                result = json.loads(response.read().decode('utf-8'))
                if result and isinstance(result, list) and len(result) > 0:
                    study_ids = result
                    break
        except Exception as e:
            logger.warning(f"Orthanc /tools/find query error for {payload}: {e}")
            continue

    if not study_ids:
        return JsonResponse({
            'success': False,
            'message': f'No DICOM studies found in Orthanc for Bill No: {invest_bill_no}. Please ensure modality has pushed images.'
        })

    # Retrieve StudyInstanceUIDs from study details
    study_instance_uids = []
    for sid in study_ids:
        try:
            study_detail_url = f"{orthanc_url}/studies/{sid}"
            req = urllib.request.Request(study_detail_url)
            if orthanc_user and orthanc_pass:
                auth_header = base64.b64encode(f"{orthanc_user}:{orthanc_pass}".encode()).decode()
                req.add_header('Authorization', f"Basic {auth_header}")
            with urllib.request.urlopen(req, timeout=5) as response:
                detail = json.loads(response.read().decode('utf-8'))
                main_tags = detail.get('MainDicomTags', {})
                siuid = main_tags.get('StudyInstanceUID')
                if siuid and siuid not in study_instance_uids:
                    study_instance_uids.append(siuid)
        except Exception as e:
            logger.warning(f"Error fetching study detail for {sid}: {e}")

    if not study_instance_uids:
        return JsonResponse({
            'success': False,
            'message': 'Study found in Orthanc but could not resolve StudyInstanceUID.'
        })

    siuid_param = ",".join(study_instance_uids)
    viewer_url = f"{ohif_url}?StudyInstanceUIDs={siuid_param}"

    return JsonResponse({
        'success': True,
        'viewerUrl': viewer_url,
        'studyInstanceUIDs': study_instance_uids,
        'orthancStudyIds': study_ids
    })


