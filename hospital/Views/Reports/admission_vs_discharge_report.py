from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
import os
import re
from datetime import datetime


def _parse_dt(dt_val):
    if not dt_val:
        return None
    if isinstance(dt_val, datetime):
        return dt_val
    if isinstance(dt_val, str):
        try:
            return datetime.fromisoformat(dt_val.replace('Z', '+00:00'))
        except Exception:
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y']:
                try:
                    return datetime.strptime(dt_val[:19], fmt)
                except Exception:
                    continue
    return None


def _ip_sort_key(ip_str):
    nums = re.findall(r'\d+', str(ip_str or ''))
    return [int(n) for n in nums] if nums else [str(ip_str or '')]


def build_admission_vs_discharge_report(start_date_str='', end_date_str='', search_query='', status_filter='all', company_filter='all', sort_order='asc'):
    """
    Core business logic to query and compile Admission vs Discharge Report.
    """
    client = None
    try:
        dt_start = None
        dt_end = None
        if start_date_str:
            try:
                dt_start = datetime.strptime(start_date_str[:10], '%Y-%m-%d')
            except Exception:
                dt_start = None
        if end_date_str:
            try:
                dt_end = datetime.strptime(end_date_str[:10], '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            except Exception:
                dt_end = None

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']

        # 1. Fetch non-cancelled admissions
        adm_query = {
            '$or': [
                {'is_cancelled': False},
                {'is_cancelled': None},
                {'is_cancelled': {'$exists': False}}
            ]
        }
        admissions = list(hms_db['hospital_admission'].find(adm_query))

        # 2. Bulk load patient names
        uhids = list(set([a.get('uhid') for a in admissions if a.get('uhid')]))
        patient_map = {}
        if uhids:
            for p in hms_db['hospital_patient'].find({'uhid': {'$in': uhids}}, {'uhid': 1, 'name': 1, 'firstName': 1, 'lastName': 1, 'gender': 1, 'age': 1}):
                u = p.get('uhid')
                name = p.get('name') or f"{p.get('firstName') or ''} {p.get('lastName') or ''}".strip() or u
                patient_map[u] = {
                    'name': name,
                    'gender': p.get('gender') or '',
                    'age': p.get('age') or ''
                }

        # 3. Bulk load discharge bills
        ip_numbers = list(set([a.get('ipNumber') for a in admissions if a.get('ipNumber')]))
        discharge_bills = {}
        if ip_numbers:
            for dbill in hms_db['hospital_dischargebilling'].find({'ip_number': {'$in': ip_numbers}, 'is_cancelled': {'$ne': True}}):
                ip_n = dbill.get('ip_number')
                if ip_n and ip_n not in discharge_bills:
                    discharge_bills[ip_n] = dbill

        now = datetime.now()
        records = []
        distinct_companies = set()

        for adm in admissions:
            ip = str(adm.get('ipNumber') or '').strip()
            if not ip:
                continue

            uhid = str(adm.get('uhid') or '').strip()
            pinfo = patient_map.get(uhid) or {}
            pat_name = pinfo.get('name') or uhid or '-'

            # Room extraction
            room_list = adm.get('room_details') or []
            active_room = next((r for r in room_list if r.get('is_roomActive')), None)
            if not active_room and room_list:
                active_room = room_list[-1]
            room_str = '-'
            if active_room:
                rno = str(active_room.get('roomNo') or '').strip()
                bno = str(active_room.get('bedNo') or '').strip()
                room_str = f"{rno} / {bno}" if (rno and bno) else (rno if rno else '-')

            # Dates
            adm_dt = _parse_dt(adm.get('admissionDateTime'))
            dis_dt = None
            is_discharged = bool(adm.get('is_discharged'))

            if is_discharged:
                dbill = discharge_bills.get(ip)
                if dbill and dbill.get('bill_date'):
                    dis_dt = _parse_dt(dbill.get('bill_date'))
                elif active_room and active_room.get('endDateTime'):
                    dis_dt = _parse_dt(active_room.get('endDateTime'))
                elif adm.get('dischargeDateTime'):
                    dis_dt = _parse_dt(adm.get('dischargeDateTime'))
                else:
                    dis_dt = _parse_dt(adm.get('lastmodified_date'))

            # Date Range Filter:
            # Matches if either admitting date or discharge date falls within [dt_start, dt_end]
            if dt_start and dt_end:
                matches_date = False
                if adm_dt:
                    adm_naive = adm_dt.replace(tzinfo=None) if hasattr(adm_dt, 'tzinfo') and adm_dt.tzinfo else adm_dt
                    start_naive = dt_start.replace(tzinfo=None)
                    end_naive = dt_end.replace(tzinfo=None)
                    if start_naive <= adm_naive <= end_naive:
                        matches_date = True
                if not matches_date and dis_dt:
                    dis_naive = dis_dt.replace(tzinfo=None) if hasattr(dis_dt, 'tzinfo') and dis_dt.tzinfo else dis_dt
                    start_naive = dt_start.replace(tzinfo=None)
                    end_naive = dt_end.replace(tzinfo=None)
                    if start_naive <= dis_naive <= end_naive:
                        matches_date = True
                if not matches_date:
                    continue

            # Status Filter
            if status_filter == 'admitted' and is_discharged:
                continue
            if status_filter == 'discharged' and not is_discharged:
                continue

            # Length of stay (No of days)
            no_of_days = 0
            if adm_dt:
                end_for_calc = dis_dt or now
                adm_naive = adm_dt.replace(tzinfo=None) if hasattr(adm_dt, 'tzinfo') and adm_dt.tzinfo else adm_dt
                end_naive = end_for_calc.replace(tzinfo=None) if hasattr(end_for_calc, 'tzinfo') and end_for_calc.tzinfo else end_for_calc
                diff = (end_naive - adm_naive).days
                no_of_days = max(1, diff) if is_discharged else max(0, diff)

            # Advance
            adv_list = adm.get('advance_payments') or []
            total_advance = sum(
                float(a.get('advance_amount') or a.get('ip_advance') or 0)
                for a in adv_list if a.get('is_advanceActive', True)
            )

            # Company Name
            comp = adm.get('insurance_company') or adm.get('company_name') or adm.get('customer_type') or 'Cash / Self'
            comp_str = str(comp).strip()
            if comp_str.lower() in ['new', 'cash', 'self', '']:
                comp_str = 'Cash / Self'
            distinct_companies.add(comp_str)

            # Company filter
            if company_filter and company_filter.lower() != 'all':
                if company_filter.lower() not in comp_str.lower():
                    continue

            # Search Query filter
            if search_query:
                haystack = f"{ip} {uhid} {pat_name} {room_str} {comp_str}".lower()
                if search_query not in haystack:
                    continue

            records.append({
                'ip_number': ip,
                'room': room_str,
                'patient_name': pat_name,
                'uhid': uhid,
                'admitting_date': adm_dt.strftime('%d/%m/%Y %I:%M %p') if adm_dt else '-',
                'admitting_date_iso': adm_dt.isoformat() if adm_dt else '',
                'discharge_date': dis_dt.strftime('%d/%m/%Y %I:%M %p') if dis_dt else 'Still Admitted',
                'discharge_date_iso': dis_dt.isoformat() if dis_dt else '',
                'is_discharged': is_discharged,
                'no_of_days': no_of_days,
                'advance': round(total_advance, 2),
                'company_name': comp_str
            })

        # Sort strictly by IPNUMBER as requested
        records.sort(key=_ip_sort_key, reverse=(sort_order == 'desc'))

        # Assign 1-based sequential Sl-No
        for idx, rec in enumerate(records, 1):
            rec['sl_no'] = idx

        # Calculate summary KPIs
        total_inpatients = len(records)
        active_count = sum(1 for r in records if not r['is_discharged'])
        discharged_count = sum(1 for r in records if r['is_discharged'])
        total_advance = sum(r['advance'] for r in records)
        avg_days = round(sum(r['no_of_days'] for r in records) / total_inpatients, 1) if total_inpatients > 0 else 0

        summary = {
            'total_inpatients': total_inpatients,
            'active_admissions': active_count,
            'discharged_count': discharged_count,
            'total_advance': round(total_advance, 2),
            'avg_length_of_stay': avg_days
        }

        return {
            'success': True,
            'report_name': 'Admission vs Discharge Report',
            'date_range': {
                'start_date': start_date_str or '',
                'end_date': end_date_str or ''
            },
            'summary': summary,
            'companies': sorted(list(distinct_companies)),
            'data': records
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}
    finally:
        if client:
            client.close()


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def admission_vs_discharge_report_view(request):
    """
    Admission vs Discharge Report API endpoint.
    """
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    search_query = request.GET.get('search', '').strip().lower()
    status_filter = request.GET.get('status', 'all').strip().lower()
    company_filter = request.GET.get('company', 'all').strip()
    sort_order = request.GET.get('sort_order', 'asc').strip().lower()

    result = build_admission_vs_discharge_report(
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        search_query=search_query,
        status_filter=status_filter,
        company_filter=company_filter,
        sort_order=sort_order
    )

    if not result.get('success'):
        return Response(result, status=500)
    return Response(result)
