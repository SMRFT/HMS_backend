from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
import os
import json
import ast
from datetime import datetime, date, timedelta
from bson import Decimal128, ObjectId

# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def parse_json_field(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        val_str = value.strip()
        if not val_str:
            return []
        try:
            return json.loads(val_str)
        except Exception:
            try:
                return ast.literal_eval(val_str)
            except Exception:
                return []
    return value if isinstance(value, list) else []


def clean_decimal(val):
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, Decimal128):
        return float(val.to_decimal())
    try:
        return float(str(val).replace(',', '').strip())
    except Exception:
        return 0.0


def parse_date_str(date_str, is_end=False):
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        if is_end:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return dt
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Unified Insurance & Credit Billing Report Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def insurance_credit_report_view(request):
    """
    Unified report aggregating:
    1. Insurance & Credit Registration / OP Bills (hospital_billing)
    2. Active and recent IP Admissions & Bed Occupancy (hospital_admission)
    3. Investigation / Lab Bills & Tests ordered (hospital_investbilling)
    4. Patient & TPA Company Details (hospital_patient & hospital_insuranceprovider)
    """
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        global_db = client['Global']

        # Extract filters from request
        start_date_param = request.GET.get('start_date')
        end_date_param = request.GET.get('end_date')
        company_filter = request.GET.get('company_code', 'all').strip()
        care_status_filter = request.GET.get('care_status', 'all').strip()  # all, ip_admitted, op_visit, discharged
        doctor_filter = request.GET.get('doctor_id', 'all').strip()
        search_query = request.GET.get('search', '').strip().lower()

        # Parse date range (default to 60 days range if not provided)
        now = datetime.now()
        dt_start = parse_date_str(start_date_param) if start_date_param else (now - timedelta(days=60))
        dt_end = parse_date_str(end_date_param, is_end=True) if end_date_param else now

        # 1. Build Doctor Mapping
        doctor_map = {}
        try:
            diag_coll = global_db['backend_diagnostics_profile']
            docs_cur = diag_coll.find(
                {},
                {"employeeId": 1, "employeeName": 1, "first_name": 1, "last_name": 1, "_id": 0}
            )
            for d in docs_cur:
                eid = str(d.get('employeeId') or '').strip()
                if eid:
                    name = d.get('employeeName') or f"{d.get('first_name', '')} {d.get('last_name', '')}".strip() or eid
                    doctor_map[eid] = name
        except Exception as e:
            print(f"Error building doctor map: {e}")

        # 2. Build Insurance Provider Mapping (company_code -> company_name)
        company_map = {}
        all_companies_list = []
        try:
            prov_cur = hms_db['hospital_insuranceprovider'].find(
                {},
                {"company_code": 1, "company_name": 1, "_id": 0}
            )
            for p in prov_cur:
                cc = str(p.get('company_code') or '').strip()
                cn = (p.get('company_name') or '').strip()
                if cc:
                    company_map[cc] = cn or cc
                    company_map[cn.lower()] = cn or cc
                    all_companies_list.append({"code": cc, "name": cn or cc})
        except Exception as e:
            print(f"Error building company map: {e}")

        # 3. Build Room Mapping (room_number -> details)
        room_map = {}
        try:
            room_cur = hms_db['hospital_room'].find(
                {},
                {"room_number": 1, "room_category": 1, "block": 1, "floor": 1, "room_type": 1, "_id": 0}
            )
            for r in room_cur:
                rno = str(r.get('room_number') or '').strip()
                if rno:
                    room_map[rno] = {
                        "room_category": r.get('room_category', 'General Ward'),
                        "block": r.get('block', 'Main Block'),
                        "floor": r.get('floor', '1'),
                        "room_type": r.get('room_type', 'Standard')
                    }
        except Exception as e:
            print(f"Error building room map: {e}")

        # 4. Fetch Admissions
        # We index admissions by uhid and by ipNumber
        admissions_by_uhid = {}
        active_adm_by_uhid = {}
        try:
            adm_cur = hms_db['hospital_admission'].find(
                {"is_cancelled": {"$ne": True}}
            )
            for adm in adm_cur:
                uhid = str(adm.get('uhid') or '').strip()
                ip_no = str(adm.get('ipNumber') or '').strip()
                is_admitted = bool(adm.get('is_admitted', False))
                is_discharged = bool(adm.get('is_discharged', False))

                # Extract room & bed occupancy
                room_no = bed_no = None
                shifts = parse_json_field(adm.get('roomShitingDetails'))
                active_shifts = [r for r in shifts if str(r.get('is_roomActive', '')).lower() in ('true', '1')]
                if active_shifts:
                    latest = active_shifts[-1]
                    room_no = latest.get('newRoomNo')
                    bed_no = latest.get('newBedNo')

                if room_no is None:
                    details = parse_json_field(adm.get('room_details'))
                    active_rooms = [r for r in details if str(r.get('is_roomActive', '')).lower() in ('true', '1')]
                    if active_rooms:
                        room_no = active_rooms[-1].get('roomNo')
                        bed_no = active_rooms[-1].get('bedNo')
                    elif details:
                        room_no = details[-1].get('roomNo')
                        bed_no = details[-1].get('bedNo')

                # Room metadata
                rm_meta = room_map.get(str(room_no), {})
                adm_doc_id = str(adm.get('admittingDoctor') or '')
                adm_doc_name = doctor_map.get(adm_doc_id, adm_doc_id or 'N/A')

                # Insurance company on admission
                ins_comp = adm.get('insurance_company') or company_map.get(adm.get('company_code')) or adm.get('company_code') or ''

                adm_info = {
                    "ipNumber": ip_no,
                    "uhid": uhid,
                    "customer_type": adm.get('customer_type', 'General'),
                    "company_code": adm.get('company_code', ''),
                    "insurance_company": ins_comp,
                    "admissionDateTime": adm.get('admissionDateTime'),
                    "admittingDoctorId": adm_doc_id,
                    "admittingDoctorName": adm_doc_name,
                    "packageName": adm.get('packageName', ''),
                    "reasonForAdmission": adm.get('reasonForAdmission', ''),
                    "is_admitted": is_admitted,
                    "is_discharged": is_discharged,
                    "room_no": str(room_no) if room_no else None,
                    "bed_no": str(bed_no) if bed_no else None,
                    "room_category": rm_meta.get('room_category', 'General Ward') if room_no else None,
                    "block": rm_meta.get('block', 'Main Block') if room_no else None,
                    "floor": rm_meta.get('floor', '1') if room_no else None,
                }

                if uhid:
                    if uhid not in admissions_by_uhid:
                        admissions_by_uhid[uhid] = []
                    admissions_by_uhid[uhid].append(adm_info)

                    if is_admitted and not is_discharged:
                        active_adm_by_uhid[uhid] = adm_info
        except Exception as e:
            print(f"Error loading admissions: {e}")

        # 5. Fetch Investigation Bills
        # Grouped by uhid and by ipNumber
        investigations_by_uhid = {}
        try:
            inv_cur = hms_db['hospital_investbilling'].find({})
            for inv in inv_cur:
                uhid = str(inv.get('uhid') or '').strip()
                if not uhid:
                    continue
                ip_no = str(inv.get('ipNumber') or '').strip()
                bill_no = inv.get('investBillNo', '')
                tot = clean_decimal(inv.get('finalPrice') or inv.get('total') or 0)
                pm = inv.get('paymentMethod', 'Cash')
                ps = inv.get('paymentStatus', 'Pending')
                b_date = inv.get('investBillDate') or inv.get('created_date')

                # Parse items
                raw_items = inv.get('item', [])
                items_list = []
                if isinstance(raw_items, list):
                    for it in raw_items:
                        if isinstance(it, dict):
                            t_name = it.get('itemName') or it.get('test_name') or 'Diagnostic Test'
                            t_price = clean_decimal(it.get('price', 0))
                            items_list.append({"name": t_name, "price": t_price})

                inv_record = {
                    "investBillNo": bill_no,
                    "ipNumber": ip_no,
                    "amount": tot,
                    "paymentMethod": pm,
                    "paymentStatus": ps,
                    "date": b_date.isoformat() if isinstance(b_date, datetime) else str(b_date or ''),
                    "items": items_list
                }

                if uhid not in investigations_by_uhid:
                    investigations_by_uhid[uhid] = []
                investigations_by_uhid[uhid].append(inv_record)
        except Exception as e:
            print(f"Error loading investigations: {e}")

        # 6. Gather target UHIDs and Patients
        # Targets:
        # a) Patients who have admissions with customer_type == 'Insurance' or company_code
        # b) Patients who have billing with payment_method in ['Insurance Credit', 'Pay Later', 'Credit', 'Insurance'] or payment_status == 'Pending' or patient customer_type == 'Insurance'
        # c) Patients with customer_type == 'Insurance'
        target_uhids = set()

        # From admissions:
        for u, adm_list in admissions_by_uhid.items():
            for a in adm_list:
                c_type = str(a.get('customer_type') or '').lower()
                if 'insurance' in c_type or a.get('insurance_company') or a.get('company_code'):
                    target_uhids.add(u)

        # From investigation credit:
        for u, inv_list in investigations_by_uhid.items():
            for inv in inv_list:
                pm = str(inv.get('paymentMethod') or '').lower()
                if 'credit' in pm or 'insurance' in pm:
                    target_uhids.add(u)

        # From hospital_billing:
        billing_query = {
            "$or": [
                {"payment_method": {"$in": ["Insurance Credit", "Pay Later", "Credit", "Insurance"]}},
                {"payment_status": "Pending"}
            ]
        }
        credit_bills_cursor = hms_db['hospital_billing'].find(billing_query)
        bills_by_uhid = {}
        for b in credit_bills_cursor:
            pid = str(b.get('patient_id') or '').strip()
            if pid:
                # In Djongo, patient_id could be uhid or patient pk. We'll map both.
                if pid not in bills_by_uhid:
                    bills_by_uhid[pid] = []
                bills_by_uhid[pid].append(b)
                target_uhids.add(pid)

        # Also pull patients with customer_type == 'Insurance'
        ins_patients_cur = hms_db['hospital_patient'].find(
            {"customer_type": {"$in": ["Insurance", "INSURANCE", "insurance"]}},
            {"uhid": 1, "id": 1, "_id": 0}
        ).limit(100)
        for p in ins_patients_cur:
            if p.get('uhid'):
                target_uhids.add(str(p['uhid']).strip())
            if p.get('id'):
                target_uhids.add(str(p['id']).strip())

        # If still empty (e.g. brand new test environment), gather all patients who have any billing or admission
        if not target_uhids:
            for u in list(admissions_by_uhid.keys())[:20]:
                target_uhids.add(u)

        # 7. Batch Fetch Patient Profiles
        patient_profiles = {}
        p_query = {
            "$or": [
                {"uhid": {"$in": list(target_uhids)}},
                {"id": {"$in": [int(x) for x in target_uhids if x.isdigit()]}}
            ]
        }
        patients_cur = hms_db['hospital_patient'].find(p_query)
        for p in patients_cur:
            u = str(p.get('uhid') or '').strip()
            pk = str(p.get('id') or '').strip()
            if u:
                patient_profiles[u] = p
            if pk:
                patient_profiles[pk] = p

        # 8. Build Unified Consolidated Records
        records = []
        seen_keys = set()

        # Iterate over all resolved patient UHIDs
        for p_key in list(target_uhids):
            profile = patient_profiles.get(p_key, {})
            uhid = profile.get('uhid') or (p_key if '/' in p_key else None)
            if not uhid:
                # Try finding in admissions
                if p_key in admissions_by_uhid:
                    uhid = p_key
                else:
                    uhid = p_key

            if uhid in seen_keys:
                continue
            seen_keys.add(uhid)

            first_name = profile.get('firstName') or profile.get('first_name') or ''
            last_name = profile.get('lastName') or profile.get('last_name') or ''
            patient_name = f"{profile.get('salutation', '')} {first_name} {last_name}".strip()
            if not patient_name:
                patient_name = f"Patient {uhid}"

            age = profile.get('age', '')
            gender = profile.get('gender', '')
            mobile = profile.get('mobilePhone') or profile.get('mobile_phone') or profile.get('emergency_contact') or 'N/A'
            customer_type = profile.get('customer_type') or 'General'

            # Admissions for this patient
            p_admissions = admissions_by_uhid.get(uhid, [])
            active_adm = active_adm_by_uhid.get(uhid)

            # Determine Care Status & Bed Occupancy
            care_status = "OP Visit"
            is_admitted = False
            ip_number = ""
            admission_date = ""
            admitting_doctor = "N/A"
            room_no = "-"
            bed_no = "-"
            room_category = "-"
            block = "-"
            floor = "-"

            if active_adm:
                care_status = "IP Admitted"
                is_admitted = True
                ip_number = active_adm.get('ipNumber', '')
                ad_dt = active_adm.get('admissionDateTime')
                admission_date = ad_dt.strftime("%d-%m-%Y %I:%M %p") if isinstance(ad_dt, datetime) else str(ad_dt or '')
                admitting_doctor = active_adm.get('admittingDoctorName', 'N/A')
                room_no = active_adm.get('room_no') or '-'
                bed_no = active_adm.get('bed_no') or '-'
                room_category = active_adm.get('room_category') or 'General Ward'
                block = active_adm.get('block') or 'Main Block'
                floor = active_adm.get('floor') or '1'
            elif p_admissions:
                latest_adm = p_admissions[-1]
                care_status = "Discharged" if latest_adm.get('is_discharged') else "IP Admitted"
                ip_number = latest_adm.get('ipNumber', '')
                ad_dt = latest_adm.get('admissionDateTime')
                admission_date = ad_dt.strftime("%d-%m-%Y %I:%M %p") if isinstance(ad_dt, datetime) else str(ad_dt or '')
                admitting_doctor = latest_adm.get('admittingDoctorName', 'N/A')
                room_no = latest_adm.get('room_no') or '-'
                bed_no = latest_adm.get('bed_no') or '-'
                room_category = latest_adm.get('room_category') or 'General Ward'
                block = latest_adm.get('block') or 'Main Block'
                floor = latest_adm.get('floor') or '1'

            # Insurance Company Resolution
            comp_code = (
                profile.get('company_code')
                or profile.get('insuranceProviderCode')
                or (active_adm.get('company_code') if active_adm else '')
                or (p_admissions[-1].get('company_code') if p_admissions else '')
                or ''
            )
            comp_name = (
                company_map.get(comp_code)
                or (active_adm.get('insurance_company') if active_adm else '')
                or (p_admissions[-1].get('insurance_company') if p_admissions else '')
                or profile.get('company_name')
                or comp_code
                or 'Direct Credit / Self'
            )

            # Registration / OP Bills
            p_bills = bills_by_uhid.get(uhid, []) or bills_by_uhid.get(str(profile.get('id', '')), [])
            op_bill_no = ""
            op_reg_fee = 0.0
            op_cons_fee = 0.0
            op_total = 0.0
            op_doctor_id = ""
            payment_status = "Pending"
            payment_method = "Insurance Credit"

            if p_bills:
                latest_b = p_bills[-1]
                op_bill_no = latest_b.get('bill_number', '')
                op_reg_fee = clean_decimal(latest_b.get('registration_fee', 0))
                op_cons_fee = clean_decimal(latest_b.get('consulting_fee', 0))
                op_total = clean_decimal(latest_b.get('total_fees', 0))
                op_doctor_id = latest_b.get('doctor_id', '')
                payment_status = latest_b.get('payment_status', 'Pending')
                payment_method = latest_b.get('payment_method', 'Insurance Credit')
            
            consulting_doctor = doctor_map.get(op_doctor_id, op_doctor_id or admitting_doctor)

            # Investigations
            p_invest = investigations_by_uhid.get(uhid, [])
            invest_total = sum(inv.get('amount', 0) for inv in p_invest)
            invest_bill_nos = [inv.get('investBillNo') for inv in p_invest if inv.get('investBillNo')]
            all_test_items = []
            for inv in p_invest:
                for it in inv.get('items', []):
                    all_test_items.append(it.get('name', 'Test'))

            # Total Claim / Credit Exposure
            total_credit = op_total + invest_total

            # Apply Filter Rules
            # 1. Company Filter
            if company_filter and company_filter != 'all':
                if comp_code != company_filter and company_filter.lower() not in comp_name.lower():
                    continue

            # 2. Care Status Filter
            if care_status_filter and care_status_filter != 'all':
                if care_status_filter == 'ip_admitted' and care_status != 'IP Admitted':
                    continue
                if care_status_filter == 'op_visit' and care_status != 'OP Visit':
                    continue
                if care_status_filter == 'discharged' and care_status != 'Discharged':
                    continue

            # 3. Doctor Filter
            if doctor_filter and doctor_filter != 'all':
                if doctor_filter not in [op_doctor_id, active_adm.get('admittingDoctorId') if active_adm else '']:
                    continue

            # 4. Search Query Filter
            if search_query:
                haystack = f"{uhid} {ip_number} {patient_name} {mobile} {comp_name} {op_bill_no} {' '.join(invest_bill_nos)}".lower()
                if search_query not in haystack:
                    continue

            records.append({
                "uhid": uhid,
                "patient_name": patient_name,
                "age_gender": f"{age} / {gender}".strip(" /"),
                "mobile": mobile,
                "customer_type": customer_type,
                "company_code": comp_code,
                "company_name": comp_name,
                "care_status": care_status,
                "is_currently_admitted": is_admitted,
                "ip_number": ip_number or "-",
                "admission_date": admission_date or "-",
                "admitting_doctor": admitting_doctor,
                "room_no": room_no,
                "bed_no": bed_no,
                "room_category": room_category,
                "block": block,
                "floor": floor,
                "op_bill_number": op_bill_no or "-",
                "consulting_doctor": consulting_doctor or "N/A",
                "registration_fee": op_reg_fee,
                "consulting_fee": op_cons_fee,
                "op_total_fees": op_total,
                "investigation_count": len(all_test_items),
                "investigation_bill_numbers": invest_bill_nos,
                "investigation_tests": all_test_items[:6],
                "investigation_total": invest_total,
                "total_credit_amount": total_credit,
                "payment_status": payment_status,
                "payment_method": payment_method
            })

        # Sort: Active IP Admitted first, then by total credit descending
        records.sort(key=lambda r: (1 if r['is_currently_admitted'] else 0, r['total_credit_amount']), reverse=True)

        # 9. Compute Summary Statistics
        summary = {
            "total_patients": len(records),
            "active_inpatients": sum(1 for r in records if r['is_currently_admitted']),
            "total_op_credit": sum(r['op_total_fees'] for r in records),
            "total_investigation_credit": sum(r['investigation_total'] for r in records),
            "total_credit_exposure": sum(r['total_credit_amount'] for r in records)
        }

        # Deduplicate company dropdown list
        unique_companies = []
        seen_c = set()
        for c in all_companies_list:
            if c['code'] not in seen_c:
                seen_c.add(c['code'])
                unique_companies.append(c)

        return Response({
            "success": True,
            "summary": summary,
            "data": records,
            "companies": unique_companies
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()

