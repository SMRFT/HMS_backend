from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
from datetime import datetime, timedelta
from pymongo import MongoClient
import pytz, os

from ..models import JRDReport

import logging
logger = logging.getLogger(__name__)

_IST = pytz.timezone("Asia/Kolkata")


 
def _to_ist(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(_IST).strftime("%Y-%m-%dT%H:%M:%S")
 
 
def _get_db():
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    return client, client['HMS']['hospital_jrdreport']
 
 
def _next_jrd_id(col, hospital_code, branch_code):
    """Sequential jrd_id per hospital+branch."""
    last = col.find_one(
        {'hospital_code': hospital_code, 'branch_code': branch_code},
        sort=[('jrd_id', -1)],
    )
    return (last['jrd_id'] + 1) if last else 1
 
 
def _serialize(doc):
    if hasattr(doc, '__dict__'):  # Django model instance
        get = lambda key, default='': getattr(doc, key, default)
    else:  # MongoDB dict
        get = lambda key, default='': doc.get(key, default)

    return {
        'jrd_id':       get('jrd_id'),
        'investBillNo': get('investBillNo', ''),
        'item_id':      get('item_id'),
        'form_no':      get('form_no', ''),
        'mtp_advice':   get('mtp_advice', ''),
        'is_active':    get('is_active', True),
    }


# ─── ANC Register ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_anc_register(request):
    try:
        from_date_str = request.GET.get('from_date')
        to_date_str   = request.GET.get('to_date')

        if not from_date_str or not to_date_str:
            return JsonResponse({'error': 'from_date and to_date are required'}, status=400)

        try:
            from_dt = datetime.strptime(from_date_str, '%Y-%m-%d')
            to_dt   = datetime.strptime(to_date_str, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
        except ValueError:
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)

        hospital_code = request.data.get('auth-hospital-code', 'system')
        branch_code   = request.data.get('auth-branch-code',   'system')

        client    = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db    = client['HMS']
        global_db = client['Global']

        report_col  = hms_db['hospital_radiologyreport']
        billing_col = hms_db['hospital_investbilling']
        patient_col = hms_db['hospital_patient']
        profile_col = global_db['backend_diagnostics_profile']

        try:
            # ── 1. Fetch approved ANC reports ─────────────────────────────────
            report_filter = {
                'is_active':   True,
                'is_approved': True,
                'type':        'ANC',
                'date':        {'$gte': from_dt, '$lte': to_dt},
            }
            if hospital_code and hospital_code != 'system':
                report_filter['hospital_code'] = hospital_code
            if branch_code and branch_code != 'system':
                report_filter['branch_code'] = branch_code

            reports = list(report_col.find(report_filter, {'_id': 0}))
            if not reports:
                return JsonResponse([], safe=False)

            # Serialize datetime fields
            for r in reports:
                for field in ['date', 'created_date', 'lastmodified_date',
                              'approved_date', 'patientIn_DateTime',
                              'scan_started_DateTime', 'dispatch_DateTime']:
                    if field in r and isinstance(r[field], datetime):
                        r[field] = _to_ist(r[field])
                if 'slot_DateTime' in r and isinstance(r['slot_DateTime'], datetime):
                    r['slot_DateTime'] = r['slot_DateTime'].strftime('%Y-%m-%dT%H:%M:%S')

            # ── 2. Collect unique bill numbers ────────────────────────────────
            bill_nos = list({r['investBillNo'] for r in reports if r.get('investBillNo')})

            # ── 3. Fetch billing records ──────────────────────────────────────
            # billing holds the real uhid, referredBy, doctor
            billing_docs = list(billing_col.find(
                {'investBillNo': {'$in': bill_nos}, 'is_active': True},
                {
                    '_id': 0,
                    'investBillNo': 1,
                    'uhid':         1,
                    'referredBy':   1,
                    'doctor':       1,
                }
            ))
            billing_map = {b['investBillNo']: b for b in billing_docs}

            # ── 4. Collect uhids from billing (report.uhid is often empty) ────
            uhid_list = list({b['uhid'] for b in billing_docs if b.get('uhid')})

            # ── 5. Collect employee IDs ───────────────────────────────────────
            # referredBy comes from billing, received/approved from report
            emp_ids = set()
            for r in reports:
                bill = billing_map.get(r.get('investBillNo'), {})
                ref  = str(bill.get('referredBy', '') or '').strip()
                appr = str(r.get('approved_by',   '') or '').strip()
                if ref.isdigit():  emp_ids.add(ref)
                if appr.isdigit(): emp_ids.add(appr)

            # ── 6. Batch-fetch employee profiles ──────────────────────────────
            emp_docs = list(profile_col.find(
                {'employeeId': {'$in': list(emp_ids)}},
                {'_id': 0, 'employeeId': 1, 'employeeName': 1, 'designation': 1}
            ))
            emp_map = {e['employeeId']: e for e in emp_docs}

            def _emp_name(emp_id):
                if not emp_id: return '—'
                sid = str(emp_id).strip()
                if sid.isdigit():
                    return emp_map.get(sid, {}).get('employeeName', sid)
                return sid

            # ── 7. Fetch patient records ──────────────────────────────────────
            patient_docs = list(patient_col.find(
                {'uhid': {'$in': uhid_list}},
                {
                    '_id': 0, 'uhid': 1,
                    'salutation': 1, 'firstName': 1, 'middleName': 1, 'lastName': 1,
                    'age': 1, 'gender': 1,
                    'permanent_address': 1, 'area': 1, 'city': 1,
                    'state': 1, 'zipcode': 1,
                    'mobilePhone': 1, 'home_phone': 1,
                    'spouse_name': 1, 'maritalStatus': 1,
                }
            ))
            patient_map = {p['uhid']: p for p in patient_docs}

            def _patient_name(p):
                if not p: return ''
                return ' '.join(x for x in [
                    p.get('salutation', ''), p.get('firstName',  ''),
                    p.get('middleName', ''), p.get('lastName',   ''),
                ] if x).strip()

            def _patient_address(p):
                if not p: return ''
                return ', '.join(x for x in [
                    p.get('permanent_address', ''), p.get('area',    ''),
                    p.get('city',              ''), p.get('state',   ''),
                    p.get('zipcode',           ''),
                ] if x)

            # ── 8. Assemble result rows ───────────────────────────────────────
            result = []
            for idx, r in enumerate(reports):
                anc  = r.get('valuedetails', {}).get('anc_fields', {}) or {}
                bill = billing_map.get(r.get('investBillNo'), {})

                # uhid: billing first (report.uhid is usually blank)
                uhid    = bill.get('uhid') or r.get('uhid') or ''
                patient = patient_map.get(uhid, {})

                # doctors
                ref_id  = str(bill.get('referredBy', '') or '').strip()
                appr_id = str(r.get('approved_by',   '') or '').strip()

                # ANC fields
                ga_usg = anc.get('ga_usg', '')   # e.g. "5W2D"

                lmp = anc.get('lmp', '')
                if lmp:
                    try:
                        lmp = datetime.strptime(lmp, '%Y-%m-%d').strftime('%d.%m.%Y')
                    except ValueError:
                        pass

                # marital status: use stored value;
                # if blank but spouse name present → "Married"
                spouse_name    = patient.get('spouse_name', '') or ''
                raw_marital    = patient.get('maritalStatus', '') or ''
                marital_status = (
                    raw_marital if raw_marital.strip()
                    else ('Married' if spouse_name.strip() else '')
                )

                invest_bill_no = r.get('investBillNo', '')
                item_id_raw    = r.get('item_id')
                item_id        = int(item_id_raw) if item_id_raw is not None else None

                result.append({
                    'key':           f"{invest_bill_no}_{item_id}",
                    'sno':           idx + 1,
                    'investBillNo':  invest_bill_no,
                    'item_id':       item_id,
                    'itemName':      r.get('itemName', ''),
                    'scanDate':      r.get('date', ''),
                    'uhid':          uhid,

                    # Patient
                    'patientName':   _patient_name(patient) or r.get('itemName', ''),
                    'age':           patient.get('age', ''),
                    'gender':        patient.get('gender', ''),
                    'address':       _patient_address(patient),
                    'phone':         patient.get('mobilePhone') or patient.get('home_phone', ''),
                    'spouseName':    spouse_name,
                    'maritalStatus': marital_status,

                    # ANC
                    'guh':           anc.get('guh', '—'),
                    'lmp':           lmp,
                    'gestAge':       ga_usg,
                    'eddUsg':        anc.get('edd_usg', ''),

                    # Doctors
                    'referredByDr':  _emp_name(ref_id),
                    'receivedByDr':  _emp_name(appr_id),

                    # Meta
                    'approvedDate':  r.get('approved_date', ''),
                    'type':          r.get('type', ''),
                })

            return JsonResponse(result, safe=False)

        finally:
            client.close()

    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

# ─── LIST ─────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def list_jrd_reports(request):
    try:
        hospital_code = request.data.get('auth-hospital-code', '')
        branch_code   = request.data.get('auth-branch-code', '')

        # djongo-safe: use __in=[True] instead of =True
        qs = JRDReport.objects.filter(is_active__in=[True])

        if hospital_code and hospital_code != 'system':
            qs = qs.filter(hospital_code=hospital_code)
        if branch_code and branch_code != 'system':
            qs = qs.filter(branch_code=branch_code)

        from_date_str = request.GET.get('from_date')
        to_date_str   = request.GET.get('to_date')
        if from_date_str and to_date_str:
            try:
                from_dt = datetime.strptime(from_date_str, '%Y-%m-%d')
                to_dt   = datetime.strptime(to_date_str, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
                qs = qs.filter(created_date__gte=from_dt, created_date__lte=to_dt)
            except ValueError:
                return JsonResponse({'error': 'Invalid date format'}, status=400)

        return JsonResponse([_serialize(o) for o in qs], safe=False)

    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


# ─── CREATE ───────────────────────────────────────────────────────────────────

@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_jrd_report(request):
    try:
        data          = request.data
        user_id       = data.get('auth-user-id', 'system')
        hospital_code = data.get('auth-hospital-code', '')
        branch_code   = data.get('auth-branch-code', '')        
        outlet_code   = data.get('auth-outlet-code', '')

        invest_bill_no = str(data.get('investBillNo', '')).strip()
        if not invest_bill_no:
            return JsonResponse({'error': 'investBillNo is required'}, status=400)

        raw_item_id = data.get('item_id')
        if raw_item_id is None or str(raw_item_id).strip() == '':
            return JsonResponse({'error': 'item_id is required'}, status=400)
        try:
            item_id = int(raw_item_id)
        except (ValueError, TypeError):
            return JsonResponse({'error': 'item_id must be an integer'}, status=400)

        form_no    = str(data.get('form_no',    '')).strip()
        mtp_advice = str(data.get('mtp_advice', '')).strip()

        # ── djongo-safe boolean filters using __in ────────────────────────────

        # 1. Active record exists → 409
        existing = JRDReport.objects.filter(
            investBillNo=invest_bill_no,
            item_id=item_id,
            is_active__in=[True],
        ).first()
        if existing:
            return JsonResponse(
                {'error': 'Record already exists. Use PATCH to update.', 'jrd_id': existing.jrd_id},
                status=409,
            )

        # 2. Soft-deleted record → restore
        deleted = JRDReport.objects.filter(
            investBillNo=invest_bill_no,
            item_id=item_id,
            is_active__in=[False],
        ).first()
        if deleted:
            deleted.form_no           = form_no
            deleted.mtp_advice        = mtp_advice
            deleted.is_active         = True
            deleted.lastmodified_by   = user_id
            deleted.lastmodified_date = timezone.now()
            deleted.save()
            return JsonResponse(
                {'jrd_id': deleted.jrd_id, 'message': 'Restored'},
                status=200,
            )

        # 3. Fresh create
        client, col = _get_db()
        try:
            jrd_id = _next_jrd_id(col, hospital_code, branch_code)
            obj = JRDReport.objects.create(...)
        finally:
            client.close()
        obj = JRDReport.objects.create(
            jrd_id        = jrd_id,
            hospital_code = hospital_code,
            branch_code   = branch_code,
            outlet_code   = outlet_code,
            investBillNo  = invest_bill_no,
            item_id       = item_id,
            form_no       = form_no,
            mtp_advice    = mtp_advice,
            is_active     = True,
            created_by    = user_id,
        )
        return JsonResponse(
            {'jrd_id': obj.jrd_id, 'message': 'Created'},
            status=201,
        )

    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


 
# ─── UPDATE ───────────────────────────────────────────────────────────────────
 
@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_jrd_report(request, jrd_id):
    client, col = _get_db()
    try:
        hospital_code = request.data.get('auth-hospital-code', '')
        branch_code   = request.data.get('auth-branch-code',   '')
        user_id       = request.data.get('auth-user-id',       'system')
 
        query = {'jrd_id': int(jrd_id), 'is_active': True}
        if hospital_code and hospital_code != 'system':
            query['hospital_code'] = hospital_code
        if branch_code and branch_code != 'system':
            query['branch_code'] = branch_code
 
        doc = col.find_one(query)
        if not doc:
            return JsonResponse({'error': f'JRD-{jrd_id} not found'}, status=404)
 
        data   = request.data
        fields = {}
        if 'form_no'    in data: fields['form_no']    = str(data['form_no']).strip()
        if 'mtp_advice' in data: fields['mtp_advice'] = str(data['mtp_advice']).strip()
 
        if not fields:
            return JsonResponse({'message': 'No fields to update'}, status=200)
 
        fields['lastmodified_by']   = user_id
        fields['lastmodified_date'] = datetime.utcnow()
 
        col.update_one({'_id': doc['_id']}, {'$set': fields})
 
        updated = col.find_one({'_id': doc['_id']}, {'_id': 0})
        return JsonResponse({**_serialize(updated), 'message': 'Updated'})
 
    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)
    finally:
        client.close()
 
 
# ─── DELETE ───────────────────────────────────────────────────────────────────
 
@csrf_exempt
@api_view(['DELETE'])
@permission_classes([HasRoleAndDataPermission])
def delete_jrd_report(request, jrd_id):
    client, col = _get_db()
    try:
        hospital_code = request.data.get('auth-hospital-code', '')
        branch_code   = request.data.get('auth-branch-code',   '')
        user_id       = request.data.get('auth-user-id',       'system')
 
        query = {'jrd_id': int(jrd_id), 'is_active': True}
        if hospital_code and hospital_code != 'system':
            query['hospital_code'] = hospital_code
        if branch_code and branch_code != 'system':
            query['branch_code'] = branch_code
 
        doc = col.find_one(query)
        if not doc:
            return JsonResponse({'error': f'JRD-{jrd_id} not found'}, status=404)
 
        col.update_one(
            {'_id': doc['_id']},
            {'$set': {
                'is_active':         False,
                'lastmodified_by':   user_id,
                'lastmodified_date': datetime.utcnow(),
            }}
        )
        return JsonResponse({'message': f'JRD-{jrd_id} deleted'})
 
    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)
    finally:
        client.close()