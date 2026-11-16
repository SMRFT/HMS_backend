from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
from bson import Decimal128, ObjectId
from datetime import datetime, timedelta
from collections import defaultdict
import os
import re

def clean_num(val):
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

def parse_date(date_str, is_end=False):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(date_str[:10], fmt)
            if is_end:
                return dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        except Exception:
            continue
    return None

def get_db():
    mongo_uri = os.getenv('GLOBAL_DB_HOST')
    if not mongo_uri:
        env_path = os.path.join(os.path.dirname(__file__), '../../../.env')
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith('GLOBAL_DB_HOST'):
                        mongo_uri = line.split('=', 1)[1].strip()
    client = MongoClient(mongo_uri)
    return client, client['HMS'], client['Global']


# ─────────────────────────────────────────────────────────────────────────────
# 1. PATIENT WISE PHARMACY IP BILL DETAILED API
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def patient_wise_pharmacy_ip_bill_api(request):
    """
    Returns itemized IP pharmacy bills for a patient matching PATIENT WISE PHARMACY IP BILL DETAILED.pdf.
    Filters: uhid, ip_number, from_date, to_date, bill_number.
    NO fallback data: if no records exist in DB, returns empty lists with 'No record found'.
    """
    client, hms_db, global_db = get_db()
    try:
        search_uhid = (request.GET.get('uhid') or '').strip()
        search_ip = (request.GET.get('ip_number') or request.GET.get('ip_no') or '').strip()
        search_bill = (request.GET.get('bill_number') or request.GET.get('bill_no') or '').strip()
        from_date_str = request.GET.get('from_date') or request.GET.get('start_date')
        to_date_str = request.GET.get('to_date') or request.GET.get('end_date')

        dt_start = parse_date(from_date_str)
        dt_end = parse_date(to_date_str, is_end=True)

        # Primary search identifier
        search_term = search_ip or search_uhid
        if not search_term and search_bill:
            # Try to resolve patient from bill
            b_sample = hms_db['hospital_pharmacybilling'].find_one({
                "$or": [{"bill_no": search_bill}, {"bill_no": re.compile(f"^{re.escape(search_bill)}$", re.IGNORECASE)}]
            })
            if b_sample:
                search_term = b_sample.get('uhid') or b_sample.get('inpatient_number')

        if not search_term:
            return Response({
                "success": True,
                "message": "No record found",
                "report_title": "PATIENT WISE PHARMACY IP BILL DETAILED",
                "patient_info": None,
                "bills": [],
                "data": [],
                "items": [],
                "summary": {}
            }, status=status.HTTP_200_OK)

        # 1. Resolve Admission & Patient Info
        adm_doc = None
        # Try finding admission by IP number or UHID
        adm_doc = hms_db['hospital_admission'].find_one(
            {"$or": [
                {"ipNumber": search_term},
                {"ipNumber": re.compile(f"^{re.escape(search_term)}$", re.IGNORECASE)},
                {"uhid": search_term},
                {"uhid": re.compile(f"^{re.escape(search_term)}$", re.IGNORECASE)}
            ]},
            sort=[("admissionDateTime", -1)]
        )

        target_ip = (adm_doc.get('ipNumber') if adm_doc else search_ip) or search_term
        target_uhid = (adm_doc.get('uhid') if adm_doc else search_uhid) or search_term

        # Fetch patient master
        patient_doc = hms_db['hospital_patient'].find_one({
            "$or": [
                {"uhid": target_uhid},
                {"uhid": re.compile(f"^{re.escape(target_uhid)}$", re.IGNORECASE)},
                {"uhid": target_ip},
                {"uhid": re.compile(f"^{re.escape(target_ip)}$", re.IGNORECASE)}
            ]
        })

        patient_name = f"{patient_doc.get('firstName', '')} {patient_doc.get('lastName', '')}".strip() if patient_doc else (adm_doc.get('patientName', '') if adm_doc else '')
        age_val = (patient_doc.get('age') if patient_doc else None) or (adm_doc.get('age') if adm_doc else '')
        gender_val = (patient_doc.get('gender') if patient_doc else 'FEMALE') or 'FEMALE'
        doc_name = (adm_doc.get('admittingDoctor') if adm_doc else '') or (adm_doc.get('consultingDoctor') if adm_doc else '') or (patient_doc.get('doctorName') if patient_doc else '')

        # Resolve Room Number from room_details
        room_no = ''
        if adm_doc:
            room_details = adm_doc.get('room_details') or []
            active_r = next((r.get('roomNo') for r in reversed(room_details) if r.get('is_roomActive')), None)
            if not active_r and room_details:
                active_r = room_details[-1].get('roomNo')
            room_no = active_r or adm_doc.get('roomNumber', '') or ''

        patient_info = {
            "uhid": target_uhid,
            "op_number": target_uhid,
            "ip_number": target_ip,
            "patient_name": patient_name,
            "age_gender": f"{age_val}/{str(gender_val).upper()}",
            "admitted_date": str(adm_doc.get('admissionDateTime', ''))[:10] if adm_doc else '',
            "discharge_date": str(adm_doc.get('dischargeDateTime', ''))[:10] if adm_doc else '',
            "room_no": room_no,
            "doctor_name": doc_name
        }

        # 2. Find linked Ward Requests for this patient to map dispatched bill items accurately
        wr_docs = list(hms_db['hospital_pharmacybilling'].find({
            "$or": [
                {"uhid": target_uhid},
                {"uhid": target_ip},
                {"inpatient_number": target_ip},
                {"inpatient_number": target_uhid}
            ],
            "is_ward_request": True
        }))

        wr_dispatch_map = {}
        for wr in wr_docs:
            for dh in (wr.get('dispatch_history') or []):
                bno = dh.get('bill_no')
                if bno:
                    item_ids = {it.get('item_id') for it in (dh.get('items') or []) if it.get('item_id')}
                    wr_dispatch_map[bno] = item_ids

        # 3. Query Dispatched / Direct IP pharmacy bills
        bill_query_or = [
            {"uhid": target_ip},
            {"uhid": target_uhid},
            {"inpatient_number": target_ip}
        ]
        if wr_dispatch_map:
            bill_query_or.append({"bill_no": {"$in": list(wr_dispatch_map.keys())}})

        raw_bills = list(hms_db['hospital_pharmacybilling'].find({
            "$or": bill_query_or,
            "is_ward_request": {"$ne": True}
        }).sort("created_date", 1))

        # Filter to only IP CREDIT / IP mode bills
        ip_bills = []
        for b in raw_bills:
            b_mode = str(b.get('billing_mode') or '').upper()
            b_type = b.get('bill_type')
            b_no = b.get('bill_no')
            if b_no in wr_dispatch_map or 'IP' in b_mode or b_type == 18:
                ip_bills.append(b)

        if not ip_bills:
            return Response({
                "success": True,
                "message": "No record found",
                "report_title": "PATIENT WISE PHARMACY IP BILL DETAILED",
                "patient_info": patient_info,
                "bills": [],
                "data": [],
                "items": [],
                "summary": {}
            }, status=status.HTTP_200_OK)

        bills_output = []
        all_flattened_items = []
        tot_taxable_grand = 0.0
        tot_cgst_grand = 0.0
        tot_sgst_grand = 0.0
        tot_net_grand = 0.0

        for b in ip_bills:
            b_no = b.get('bill_no') or f"PH_{b.get('Bill_id')}"
            if search_bill and search_bill.lower() not in b_no.lower():
                continue

            raw_date = b.get('bill_date') or b.get('created_date')
            b_dt = None
            if isinstance(raw_date, datetime):
                b_dt = raw_date
            elif isinstance(raw_date, str):
                try:
                    b_dt = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                except Exception:
                    b_dt = parse_date(raw_date[:10])

            # Apply date filters
            if dt_start and b_dt:
                b_date_only = b_dt.date() if hasattr(b_dt, 'date') else b_dt
                s_date_only = dt_start.date() if hasattr(dt_start, 'date') else dt_start
                e_date_only = dt_end.date() if hasattr(dt_end, 'date') else dt_end
                if not (s_date_only <= b_date_only <= e_date_only):
                    continue

            b_date_str = b_dt.strftime("%d/%m/%Y") if b_dt else ""

            # Check if this bill originated from a ward request with specific dispatched items
            allowed_ids = wr_dispatch_map.get(b_no)

            raw_items = b.get('medicine_particulars') or b.get('items') or []
            items_list = []
            tax_slab_map = {}
            b_taxable_tot = 0.0
            b_cgst_tot = 0.0
            b_sgst_tot = 0.0
            b_net_tot = 0.0

            for itm in raw_items:
                it_id = itm.get('item_id')
                if allowed_ids and it_id not in allowed_ids:
                    continue

                part_name = itm.get('item_name') or itm.get('name') or "MEDICINE"
                qty = clean_num(itm.get('qty') or 1)
                price = clean_num(itm.get('price') or 0)
                calc_price = clean_num(itm.get('calculated_price') or (price * qty))
                batch = itm.get('batch_number') or itm.get('batch') or ""
                exp = itm.get('expiry_date') or itm.get('expiry') or ""
                hsn = str(itm.get('hsn_code') or itm.get('hsn') or "300490")

                # In Hospital Pharmacy Bills: calculated_price is the taxable base amount
                taxable = calc_price

                # Pharmacy medicines standard: 2.5% CGST + 2.5% SGST = 5% GST
                cgst_pct = clean_num(itm.get('cgst_pct') or 2.5)
                sgst_pct = clean_num(itm.get('sgst_pct') or 2.5)

                cgst = round(taxable * (cgst_pct / 100.0), 2)
                sgst = round(taxable * (sgst_pct / 100.0), 2)
                item_amt = round(taxable + cgst + sgst, 2)

                b_taxable_tot += taxable
                b_cgst_tot += cgst
                b_sgst_tot += sgst
                b_net_tot += item_amt

                slab_key = f"{int(cgst_pct + sgst_pct)}%"
                if slab_key not in tax_slab_map:
                    tax_slab_map[slab_key] = {"tax_slab": slab_key, "taxable_value": 0.0, "cgst": 0.0, "sgst": 0.0, "total_tax": 0.0}

                tax_slab_map[slab_key]["taxable_value"] += taxable
                tax_slab_map[slab_key]["cgst"] += cgst
                tax_slab_map[slab_key]["sgst"] += sgst
                tax_slab_map[slab_key]["total_tax"] += (cgst + sgst)

                row_item = {
                    "sl_no": len(items_list) + 1,
                    "bill_date": b_date_str,
                    "bill_no": b_no,
                    "qty": int(qty),
                    "particulars": part_name,
                    "batch": batch,
                    "expiry": exp,
                    "amount": item_amt,
                    "hsn": hsn,
                    "cgst_pct": cgst_pct,
                    "cgst": cgst,
                    "cgst_amt": cgst,
                    "sgst_pct": sgst_pct,
                    "sgst": sgst,
                    "sgst_amt": sgst,
                    "taxable_amt": taxable
                }
                items_list.append(row_item)
                all_flattened_items.append(row_item)

            if not items_list:
                continue

            b_taxable_tot = round(b_taxable_tot, 2)
            b_cgst_tot = round(b_cgst_tot, 2)
            b_sgst_tot = round(b_sgst_tot, 2)
            b_gst_tot = round(b_cgst_tot + b_sgst_tot, 2)
            b_net_tot = round(b_net_tot, 2)

            tot_taxable_grand += b_taxable_tot
            tot_cgst_grand += b_cgst_tot
            tot_sgst_grand += b_sgst_tot
            tot_net_grand += b_net_tot

            bills_output.append({
                "bill_no": b_no,
                "bill_date": b_date_str,
                "items": items_list,
                "tax_summary": list(tax_slab_map.values()),
                "taxable_amt": b_taxable_tot,
                "cgst_amt": b_cgst_tot,
                "sgst_amt": b_sgst_tot,
                "total_gst": b_gst_tot,
                "net_amount": b_net_tot,
                "bill_total": b_net_tot,
                "bill_net": b_net_tot
            })

        tot_taxable_grand = round(tot_taxable_grand, 2)
        tot_cgst_grand = round(tot_cgst_grand, 2)
        tot_sgst_grand = round(tot_sgst_grand, 2)
        tot_net_grand = round(tot_net_grand, 2)

        return Response({
            "success": True,
            "message": "Success",
            "report_title": "PATIENT WISE PHARMACY IP BILL DETAILED",
            "patient_info": patient_info,
            "bills": bills_output,
            "data": all_flattened_items,
            "items": all_flattened_items,
            "grand_total": tot_net_grand,
            "summary": {
                "taxable_amount": tot_taxable_grand,
                "cgst_amount": tot_cgst_grand,
                "sgst_amount": tot_sgst_grand,
                "total_gst": round(tot_cgst_grand + tot_sgst_grand, 2),
                "gross_amount": tot_net_grand,
                "net_amount": tot_net_grand
            }
        }, status=status.HTTP_200_OK)
    finally:
        client.close()




# ─────────────────────────────────────────────────────────────────────────────
# 2. LAB ABSTRACT REPORT DETAILED API
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def lab_abstract_api(request):
    """
    Returns Lab Abstract Report Detailed voucher matching Lab Abstract Report Detailed.pdf.
    Filters: ip_number, uhid, from_date, to_date.
    NO fallback data: returns empty list if no records exist in DB.
    """
    client, hms_db, global_db = get_db()
    try:
        ip_number = request.GET.get('ip_number', '').strip()
        uhid = request.GET.get('uhid', '').strip()
        from_date_str = request.GET.get('from_date') or request.GET.get('start_date')
        to_date_str = request.GET.get('to_date') or request.GET.get('end_date')

        search_term = ip_number or uhid
        if not search_term:
            return Response({
                "success": True,
                "message": "No record found",
                "report_title": "Lab Abstract Report Detailed",
                "patient_info": None,
                "patient": None,
                "data": [],
                "items": [],
                "total_amount": 0.0,
                "summary": {}
            }, status=status.HTTP_200_OK)

        # 1. Resolve Admission & Patient Info
        adm = hms_db['hospital_admission'].find_one(
            {"$or": [
                {"ipNumber": search_term},
                {"ipNumber": re.compile(f"^{re.escape(search_term)}$", re.IGNORECASE)},
                {"uhid": search_term},
                {"uhid": re.compile(f"^{re.escape(search_term)}$", re.IGNORECASE)}
            ]},
            sort=[("admissionDateTime", -1)]
        )

        target_ip = (adm.get('ipNumber') if adm else '') or ip_number or search_term
        target_uhid = (adm.get('uhid') if adm else '') or uhid or search_term

        pat = hms_db['hospital_patient'].find_one({
            "$or": [
                {"uhid": target_uhid},
                {"uhid": re.compile(f"^{re.escape(target_uhid)}$", re.IGNORECASE)},
                {"uhid": target_ip},
                {"uhid": re.compile(f"^{re.escape(target_ip)}$", re.IGNORECASE)}
            ]
        })

        pname = f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip() if pat else (adm.get('patientName', '') if adm else '')
        doc_name = (adm.get('admittingDoctor') if adm else '') or (adm.get('consultingDoctor') if adm else '') or (pat.get('doctorName') if pat else '')

        patient_info = {
            "patient_name": pname,
            "ip_number": target_ip,
            "op_number": target_uhid,
            "uhid": target_uhid,
            "doctor_name": doc_name
        }

        # 2. Query Bills for this IP Admission
        dt_start = parse_date(from_date_str)
        dt_end = parse_date(to_date_str, is_end=True)

        bills = []
        if target_ip:
            ip_q = {"$or": [{"ipNumber": target_ip}, {"ip_number": target_ip}]}
            if dt_start and dt_end:
                ip_q_dated = dict(ip_q)
                ip_q_dated["investBillDate"] = {"$gte": dt_start, "$lte": dt_end}
                bills = list(hms_db['hospital_investbilling'].find(ip_q_dated))

            # Fallback to all admission bills if date filter yields 0
            if not bills:
                bills = list(hms_db['hospital_investbilling'].find(ip_q))

        if not bills and target_uhid:
            uhid_q = {"uhid": target_uhid}
            if dt_start and dt_end:
                uhid_q["investBillDate"] = {"$gte": dt_start, "$lte": dt_end}
            elif adm and adm.get('admissionDateTime'):
                uhid_q["investBillDate"] = {"$gte": adm.get('admissionDateTime')}
            bills = list(hms_db['hospital_investbilling'].find(uhid_q))

        # Sort bills chronologically then by bill number
        bills.sort(key=lambda b: (str(b.get('investBillDate', ''))[:10], str(b.get('investBillNo', ''))))

        records = []
        sno = 1
        tot_amt = 0.0

        for b in bills:
            b_no = b.get('investBillNo') or b.get('bill_no') or b.get('billTypeNo') or f"INV262700{sno}"
            b_date = b.get('investBillDate') or b.get('bill_date')
            b_date_str = b_date.strftime("%d/%m/%Y") if isinstance(b_date, datetime) else str(b_date)[:10]

            for it in (b.get('item') or b.get('items') or []):
                btype = str(it.get('billTypeNo') or b.get('billTypeNo') or '').strip().upper()
                # Filter: Only items prefixed with 'LAB' (e.g. LAB01, LAB03)
                if not btype.startswith('LAB'):
                    continue

                item_name = (it.get('itemName') or it.get('item_name') or "DIAGNOSTIC TEST").strip()
                if item_name.endswith(' REPORT'):
                    item_name = item_name[:-7].strip()

                cost = clean_num(it.get('price') or it.get('rate') or it.get('total') or 0.0)
                qty = 1
                amt = round(cost * qty, 2)

                records.append({
                    "slno": sno,
                    "bill_date": b_date_str,
                    "bill_number": b_no,
                    "itemname": item_name,
                    "qty": qty,
                    "item_cost": cost,
                    "bill_amount": amt,
                    "billTypeNo": btype
                })
                tot_amt += amt
                sno += 1

        tot_amt = round(tot_amt, 2)

        return Response({
            "success": True,
            "message": "Success" if records else "No record found",
            "report_title": "Lab Abstract Report Detailed",
            "patient_info": patient_info,
            "patient": patient_info,
            "data": records,
            "items": records,
            "total_amount": tot_amt,
            "summary": {
                "total_tests": len(records),
                "total_amount": tot_amt
            }
        }, status=status.HTTP_200_OK)
    finally:
        client.close()

# Alias for backwards compatibility with urls.py
lab_abstract_report_api = lab_abstract_api




# ─────────────────────────────────────────────────────────────────────────────
# 3. CURRENT OCCUPANCY LIST (COMPANYWISE) API
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def occupancy_company_wise_api(request):
    """
    Returns Current occupancy list (companywise) matching Current occupancy list (companywise).pdf.
    Filters: company_name, outlet_name.
    Optimized for sub-second execution with batch Mongo queries and projections.
    """
    client, hms_db, global_db = get_db()
    try:
        company_filter = request.GET.get('company_name', 'ALL').strip()
        outlet_filter = request.GET.get('outlet_name', 'ALL').strip()

        # Query active admitted inpatients from MongoDB
        query = {"$or": [{"is_admitted": True}, {"is_discharged": False}]}
        if outlet_filter and outlet_filter.upper() != 'ALL':
            query["outlet_code"] = outlet_filter

        fields = {
            "ipNumber": 1, "uhid": 1, "patientName": 1, "company_name": 1,
            "insurance_company": 1, "admissionDateTime": 1, "created_date": 1,
            "roomNumber": 1, "bedNumber": 1, "room_details": 1, "outlet_code": 1
        }
        live_admissions = list(hms_db['hospital_admission'].find(query, fields))

        # Batch fetch patient demographics to avoid N+1 queries
        uhids = list(set([a.get('uhid') for a in live_admissions if a.get('uhid')]))
        pat_map = {}
        if uhids:
            pat_cursor = hms_db['hospital_patient'].find(
                {"uhid": {"$in": uhids}},
                {"uhid": 1, "firstName": 1, "lastName": 1, "age": 1, "gender": 1,
                 "fatherName": 1, "husbandName": 1, "permanent_address": 1, "guardian_name": 1}
            )
            for p in pat_cursor:
                pat_map[p.get('uhid')] = p

        raw_occupancy = []
        for adm in live_admissions:
            cname = (adm.get('insurance_company') or adm.get('company_name') or 'PRIVATE / CASH').strip()
            if not cname or cname == 'N':
                cname = 'PRIVATE / CASH'

            if company_filter and company_filter.upper() != 'ALL':
                if company_filter.upper() not in cname.upper():
                    continue

            uhid = adm.get('uhid')
            pat = pat_map.get(uhid)

            pname = f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip() if pat else (adm.get('patientName') or '')
            age_gender = f"{pat.get('age', '')} Yrs / {pat.get('gender', '')}".strip(' /') if pat else ""
            rel_name = pat.get('fatherName') or pat.get('husbandName') or pat.get('guardian_name') if pat else ''
            rel = f"S/o / W/o / C/o {rel_name}".strip() if rel_name else ""
            addr = pat.get('permanent_address', '') if pat else ""

            adm_dt = adm.get('admissionDateTime') or adm.get('created_date')
            adm_dt_str = adm_dt.strftime("%d/%m/%Y") if isinstance(adm_dt, datetime) else str(adm_dt or '')[:10]

            # Room details
            active_room = None
            r_details = adm.get('room_details') or []
            if isinstance(r_details, list):
                for r in r_details:
                    if isinstance(r, dict) and r.get('is_roomActive'):
                        active_room = r
                        break
                if not active_room and r_details and isinstance(r_details[-1], dict):
                    active_room = r_details[-1]

            room_no = (active_room.get('roomNo') if active_room else None) or adm.get('roomNumber') or 'General'
            bed_no = (active_room.get('bedNo') if active_room else None) or adm.get('bedNumber') or ''
            room_display = f"{room_no} / {bed_no}" if bed_no else str(room_no)

            r_str = str(room_no).upper()
            if 'MICU' in r_str: floor = "MICU"
            elif 'SICU' in r_str: floor = "SICU"
            elif 'ICU' in r_str: floor = "ICU"
            elif 'DAY' in r_str: floor = "DAY CARE"
            elif r_str.startswith('1') or 'S-1' in r_str or 'SR-1' in r_str or '1ST' in r_str: floor = "1ST FLOOR"
            elif r_str.startswith('2') or 'S-2' in r_str or 'SR-2' in r_str or '2ND' in r_str: floor = "2ND FLOOR"
            elif r_str.startswith('3') or 'S-3' in r_str or 'SR-3' in r_str or '3RD' in r_str: floor = "3RD FLOOR"
            elif r_str.startswith('4') or 'S-4' in r_str or 'SR-4' in r_str or '4TH' in r_str: floor = "4TH FLOOR"
            elif r_str.startswith('5') or 'S-5' in r_str or 'SR-5' in r_str or '5TH' in r_str: floor = "5TH FLOOR"
            else: floor = "GENERAL WARD"

            raw_occupancy.append({
                "company_name": cname,
                "floor": floor,
                "ip_number": adm.get('ipNumber', ''),
                "op_number": uhid or '',
                "patient_name": pname,
                "age_gender": age_gender,
                "relative_info": rel,
                "relation": rel,
                "address": addr,
                "admitting_date": adm_dt_str,
                "room_number": room_display
            })

        # Build Hierarchical structure: Company -> Floor -> items
        grouped = {}
        for r in raw_occupancy:
            comp = r['company_name']
            fl = r['floor']
            if comp not in grouped:
                grouped[comp] = {}
            if fl not in grouped[comp]:
                grouped[comp][fl] = []
            grouped[comp][fl].append(r)

        companies_list = list(hms_db['hospital_insuranceprovider'].find({}, {"company_name": 1, "_id": 0}))
        company_names = sorted(list(set([c.get('company_name') for c in companies_list if c.get('company_name')] + list(grouped.keys()))))

        return Response({
            "success": True,
            "message": "Success" if raw_occupancy else "No record found",
            "report_title": "Current occupancy list (companywise)",
            "columns": ["OPNUMBER", "PATIENT NAME", "AGE/GENDER", "RELATION", "ADDRESS", "ADMITTING DATE", "ROOM/BED NUMBER"],
            "data": raw_occupancy,
            "grouped_data": grouped,
            "companies": company_names,
            "total_occupied_beds": len(raw_occupancy),
            "total_beds_occupied": len(raw_occupancy)
        }, status=status.HTTP_200_OK)
    finally:
        client.close()




# ─────────────────────────────────────────────────────────────────────────────
# 4. INSURANCE BILLS STATUS API
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def insurance_bills_status_api(request):
    """
    Returns Insurance Bills Status Report matching Insurance Bills Status.pdf.
    Filters: from_date, to_date, company_name.
    NO fallback data: returns live data from MongoDB or empty structure with 'No record found'.
    """
    client, hms_db, global_db = get_db()
    try:
        from_date_str = request.GET.get('from_date') or request.GET.get('start_date')
        to_date_str = request.GET.get('to_date') or request.GET.get('end_date')
        company_filter = request.GET.get('company_name', 'ALL').strip()

        dt_start = parse_date(from_date_str)
        dt_end = parse_date(to_date_str, is_end=True)

        query = {}
        if dt_start and dt_end:
            query["$or"] = [
                {"bill_date": {"$gte": dt_start, "$lte": dt_end}},
                {"created_date": {"$gte": dt_start, "$lte": dt_end}},
                {"admissionDateTime": {"$gte": dt_start, "$lte": dt_end}}
            ]

        bills = list(hms_db['hospital_dischargebilling'].find(query))
        grouped = {}
        tot_bill = tot_settled = tot_tds = tot_paid = tot_disallowed = tot_due = 0.0

        for b in bills:
            comp = (b.get('company_name') or b.get('insurance_company') or 'PRIVATE / CASH').strip()
            if company_filter and company_filter.upper() != 'ALL':
                if company_filter.upper() not in comp.upper():
                    continue

            if comp not in grouped:
                grouped[comp] = []

            b_date = b.get('bill_date') or b.get('created_date')
            b_date_str = b_date.strftime("%d/%m/%Y") if isinstance(b_date, datetime) else str(b_date)[:10]

            b_amt = clean_num(b.get('total_amount') or b.get('bill_amount') or b.get('net_amount'))
            s_amt = clean_num(b.get('settled_amount') or 0.0)
            d_amt = clean_num(b.get('disallowed_amount') or 0.0)
            due_amt = clean_num(b.get('due_amount') or (b_amt - s_amt - d_amt))

            tot_bill += b_amt
            tot_settled += s_amt
            tot_disallowed += d_amt
            tot_due += due_amt

            grouped[comp].append({
                "company_name": comp,
                "bill_date": b_date_str,
                "op_number": b.get('uhid', ''),
                "ip_number": b.get('ip_number') or b.get('ipNumber', ''),
                "bill_id": b.get('bill_no') or b.get('bill_id', ''),
                "patient_name": b.get('patient_name', ''),
                "card_number": b.get('card_number', '-'),
                "service_no": b.get('service_no', '-'),
                "claim_reference": b.get('claim_reference', '-'),
                "place": b.get('place', 'SALEM'),
                "bill_amount": b_amt,
                "despatch_date": str(b.get('despatch_date', '-')),
                "settlement_date": str(b.get('settlement_date', '-')),
                "settled_amount": s_amt,
                "tds": clean_num(b.get('tds') or 0.0),
                "paid_by_patient": clean_num(b.get('advance_amount') or b.get('paid_by_patient') or 0.0),
                "disallowed_amount": d_amt,
                "due_amount": due_amt,
                "settlement_duration": b.get('settlement_duration', '-')
            })

        companies = list(hms_db['hospital_insuranceprovider'].find({}, {"company_name": 1, "_id": 0}))
        company_names = sorted(list(set([c.get('company_name') for c in companies if c.get('company_name')] + list(grouped.keys()))))

        return Response({
            "success": True,
            "message": "Success" if grouped else "No record found",
            "report_title": "Insurance Bills Status Report",
            "header": {
                "hospital_name": "SHANMUGA HOSPITAL LIMITED",
                "hospital_address": "51/24, Saradha College Road, Salem - 636007"
            },
            "columns": ["Bill date", "OP Number", "IP Number", "Bill ID", "Patient Name", "Card Number", "Service No", "Claim Reference", "Place", "Bill Amount", "Despatch Date", "Settlement Date", "Settled Amount", "TDS", "Paid By Patient", "Disallowed Amount", "DUE", "Settlement Duration"],
            "grouped_data": grouped,
            "companies": company_names,
            "grand_total": {
                "total_bills": sum(len(v) for v in grouped.values()),
                "total_bill_amount": round(tot_bill, 2),
                "total_settled_amount": round(tot_settled, 2),
                "total_tds": round(tot_tds, 2),
                "total_paid_by_patient": round(tot_paid, 2),
                "total_disallowed_amount": round(tot_disallowed, 2),
                "total_due_amount": round(tot_due, 2)
            }
        }, status=status.HTTP_200_OK)
    finally:
        client.close()




# ─────────────────────────────────────────────────────────────────────────────
# 5. INSURANCE BILLS STATUS (REPORT BRANCH WISE) DUES API
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def insurance_branch_dues_api(request):
    """
    Returns Insurance Bills Status Report (Branch Wise Dues) matching Insurance Bills Status(Report Branch Wise) Dues.pdf.
    Filters: from_date, to_date, company_name.
    NO fallback data.
    """
    client, hms_db, global_db = get_db()
    try:
        from_date_str = request.GET.get('from_date') or request.GET.get('start_date')
        to_date_str = request.GET.get('to_date') or request.GET.get('end_date')
        company_filter = request.GET.get('company_name', 'ALL').strip()

        dt_start = parse_date(from_date_str)
        dt_end = parse_date(to_date_str, is_end=True)

        query = {}
        if dt_start and dt_end:
            query["$or"] = [
                {"bill_date": {"$gte": dt_start, "$lte": dt_end}},
                {"created_date": {"$gte": dt_start, "$lte": dt_end}}
            ]

        bills = list(hms_db['hospital_dischargebilling'].find(query))
        grouped = {}
        tot_bill = tot_advance = tot_settled = tot_tds = tot_paid = tot_disallowed = tot_due = 0.0

        for b in bills:
            comp = (b.get('company_name') or b.get('insurance_company') or 'OTHER').strip()
            branch = (b.get('branch_code') or b.get('branch') or 'PVT').strip()

            if company_filter and company_filter.upper() != 'ALL':
                if company_filter.upper() not in comp.upper():
                    continue

            if comp not in grouped:
                grouped[comp] = {}
            if branch not in grouped[comp]:
                grouped[comp][branch] = []

            b_amt = clean_num(b.get('total_amount') or b.get('bill_amount') or b.get('net_amount'))
            adv = clean_num(b.get('advance_amount') or 0.0)
            s_amt = clean_num(b.get('settled_amount') or 0.0)
            d_amt = clean_num(b.get('disallowed_amount') or 0.0)
            due_amt = clean_num(b.get('due_amount') or (b_amt - s_amt - d_amt))

            tot_bill += b_amt
            tot_advance += adv
            tot_settled += s_amt
            tot_disallowed += d_amt
            tot_due += due_amt

            b_date = b.get('bill_date') or b.get('created_date')
            b_date_str = b_date.strftime("%d/%m/%Y") if isinstance(b_date, datetime) else str(b_date)[:10]

            grouped[comp][branch].append({
                "slno": len(grouped[comp][branch]) + 1,
                "bill_date": b_date_str,
                "ip_number": b.get('ip_number') or b.get('ipNumber', ''),
                "bill_id": b.get('bill_no') or b.get('bill_id', ''),
                "sh_bill_number": b.get('sh_bill_number', ''),
                "patient_name": b.get('patient_name', ''),
                "admitting_date": str(b.get('admission_date', '')),
                "discharge_date": str(b.get('discharge_date', '')),
                "card_number": b.get('card_number', '-'),
                "service_no": b.get('service_no', '-'),
                "claim_reference": b.get('claim_reference', '-'),
                "place": b.get('place', 'SALEM'),
                "bill_amount": b_amt,
                "advance": adv,
                "despatch_date": str(b.get('despatch_date', '-')),
                "settlement_date": str(b.get('settlement_date', '-')),
                "settled_amount": s_amt,
                "tds": clean_num(b.get('tds') or 0.0),
                "paid_by_patient": clean_num(b.get('paid_by_patient') or 0.0),
                "disallowed_amount": d_amt,
                "due_amount": due_amt,
                "settlement_duration": b.get('settlement_duration', '-')
            })

        companies = list(hms_db['hospital_insuranceprovider'].find({}, {"company_name": 1, "_id": 0}))
        company_names = sorted(list(set([c.get('company_name') for c in companies if c.get('company_name')] + list(grouped.keys()))))
        total_bills_count = sum(sum(len(items) for items in branches.values()) for branches in grouped.values())

        return Response({
            "success": True,
            "message": "Success" if grouped else "No record found",
            "report_title": "Insurance Bills Status Report (Branch Wise Dues)",
            "header": {
                "hospital_name": "SHANMUGA HOSPITAL LIMITED",
                "hospital_address": "51/24, Saradha College Road, Salem - 636007"
            },
            "columns": ["Sl No", "Bill date", "IP Number", "Bill ID", "Sh Bill Number", "Patient Name", "Admitting Date", "Discharge Date", "Card Number", "Service No", "Claim Reference", "Place", "Bill Amount", "Advance", "Despatch Date", "Settlement Date", "Settled Amount", "TDS", "Paid By Patient", "Disallowed Amount", "DUE", "Settlement Duration"],
            "grouped_data": grouped,
            "companies": company_names,
            "grand_total": {
                "total_bills": total_bills_count,
                "total_bill_amount": round(tot_bill, 2),
                "total_advance": round(tot_advance, 2),
                "total_settled_amount": round(tot_settled, 2),
                "total_tds": round(tot_tds, 2),
                "total_paid_by_patient": round(tot_paid, 2),
                "total_disallowed_amount": round(tot_disallowed, 2),
                "total_due_amount": round(tot_due, 2)
            }
        }, status=status.HTTP_200_OK)
    finally:
        client.close()




# ─────────────────────────────────────────────────────────────────────────────
# 6. COMPANY WISE REGISTRATION API
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# 6. COMPANY WISE REGISTRATION API
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def companywise_registration_api(request):
    """
    Returns patient registration details grouped by Date and Company matching Company wise registration.pdf.
    Filters: from_date, to_date, company_name.
    NO fallback data: returns live records or empty structure with 'No record found'.
    """
    client, hms_db, global_db = get_db()
    try:
        from_date_str = request.GET.get('from_date') or request.GET.get('start_date')
        to_date_str = request.GET.get('to_date') or request.GET.get('end_date')
        company_filter = request.GET.get('company_name', 'ALL').strip()

        dt_start = parse_date(from_date_str)
        dt_end = parse_date(to_date_str, is_end=True)

        if not dt_start or not dt_end:
            dt_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            dt_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)

        # 1. Build company code/name dictionary from hospital_insuranceprovider
        company_map = {}
        for p in hms_db.hospital_insuranceprovider.find({}, {"company_code": 1, "company_name": 1}):
            code = str(p.get('company_code') or '').strip()
            name = str(p.get('company_name') or '').strip()
            if code and name:
                company_map[code] = name
                company_map[code.lstrip('0')] = name

        # Canonical hospital scheme codes & standard aliases
        company_map.update({
            '000030': 'CGHS CREDIT',
            '30': 'CGHS CREDIT',
            '100066': 'CGHS CREDIT',
            '000031': 'CGHS CASH',
            '31': 'CGHS CASH',
            '046': 'CGHS CASH',
            '100002': 'ECHS',
            '001': 'ECHS',
            '100059': 'RAILWAY CTSE',
            '100003': 'RAILWAY',
            '100004': 'TNCMCHIS',
            '002': 'TNCMCHIS',
            '1': 'SELF PACKAGE',
            '100018': 'MEDI ASSIST',
            '4': 'M.A.GOVT EMPLOYEE',
            '6': 'M.A.PENSIONER',
            '100006': 'ESI',
            '100034': 'ESIC',
            '100049': 'VIDAL HEALTH',
            '100026': 'BAJAJ ALLIANZ & ALLIED INSURANCE'
        })

        def normalize_comp(c):
            if not c:
                return None
            c_str = str(c).strip()
            if c_str in company_map:
                return company_map[c_str]
            c_up = c_str.upper()
            if 'CGHS' in c_up:
                return 'CGHS CREDIT' if 'CREDIT' in c_up else 'CGHS CASH'
            if 'ECHS' in c_up or 'ECSH' in c_up:
                return 'ECHS'
            if 'RAILWAY' in c_up:
                return 'RAILWAY CTSE'
            if 'TNCMCHIS' in c_up or 'CHIEF MINISTER' in c_up or 'CMCHIS' in c_up:
                return 'TNCMCHIS'
            if 'M.A.GOVT' in c_up or 'M.A. GOVT' in c_up:
                return 'M.A.GOVT EMPLOYEE'
            if 'M.A.PENSION' in c_up or 'M.A. PENSION' in c_up:
                return 'M.A.PENSIONER'
            if 'MEDI ASSIST' in c_up:
                return 'MEDI ASSIST'
            if 'VIDAL' in c_up:
                return 'VIDAL HEALTH'
            if 'SELF' in c_up and 'PACKAGE' in c_up:
                return 'SELF PACKAGE'
            if 'BAJAJ' in c_up:
                return 'BAJAJ ALLIANZ & ALLIED INSURANCE'
            if 'STAR' in c_up:
                return 'STAR HEALTH AND ALLIED INSURANCE LTD'
            if 'MANIPAL' in c_up:
                return 'MANIPAL CIGNA'
            if 'ESI' in c_up:
                return 'ESI'
            return c_str

        def resolve_company_entry(uhid, pat, adms, claims, mems, visits, bill=None, adm=None):
            # From admission record if direct
            if adm:
                c_code = str(adm.get('company_code') or '').strip()
                if c_code in company_map:
                    return company_map[c_code]
                if adm.get('insurance_company') and str(adm.get('insurance_company')).strip() not in ['', 'GENERAL']:
                    return normalize_comp(adm.get('insurance_company'))
                if str(adm.get('customer_type') or '').upper() == 'GENERAL':
                    return 'SELF PACKAGE'

            # From bill record if direct
            if bill:
                c_code = str(bill.get('company_code') or '').strip()
                if c_code in company_map:
                    return company_map[c_code]
                if bill.get('company_name') and str(bill.get('company_name')).strip() not in ['', 'None', 'GENERAL', 'PRIVATE / CASH']:
                    return normalize_comp(bill.get('company_name'))

            # From patient doc
            p_code = str((pat or {}).get('company_code') or '').strip()
            if p_code in company_map:
                return company_map[p_code]
            p_name = (pat or {}).get('company_name')
            if p_name and str(p_name).strip() not in ['', 'None', 'GENERAL', 'PRIVATE / CASH', 'N']:
                return normalize_comp(p_name)

            # From historical admissions for this uhid
            for a in adms:
                code = str(a.get('company_code') or '').strip()
                if code in company_map:
                    return company_map[code]
                if a.get('insurance_company') and str(a.get('insurance_company')).strip() not in ['', 'GENERAL']:
                    return normalize_comp(a.get('insurance_company'))

            # From claims for this uhid
            for cl in claims:
                c_val = str(cl.get('insurance_company') or cl.get('insurance_id') or '').strip()
                if c_val in company_map:
                    return company_map[c_val]
                if c_val and c_val not in ['None', '']:
                    return normalize_comp(c_val)

            # From member visits
            for v in visits:
                v_code = str(v.get('sh_company_code') or '').strip()
                if v_code in company_map:
                    return company_map[v_code]

            # From insurance members
            for mem in mems:
                itype = str(mem.get('insurance_type') or '').strip()
                if itype in company_map:
                    return company_map[itype]
                mno = str(mem.get('member_number') or '').upper()
                if mno.startswith('CR'):
                    return 'CGHS CASH'
                if mno.startswith('TK'):
                    return 'TNCMCHIS'
                if mno.startswith('GE'):
                    return 'ECHS'
                if mno.startswith('SP'):
                    return 'SELF PACKAGE'

            # Address keywords
            addr = str((pat or {}).get('permanent_address') or '').upper()
            if 'RAILWAY' in addr or 'QUATERS' in addr or 'QUTERS' in addr or 'ATHUR' in addr:
                return 'RAILWAY CTSE'
            if 'ECHS' in addr:
                return 'ECHS'

            # Customer type Insurance fallback
            c_type = str((bill or {}).get('customer_type') or (pat or {}).get('customer_type') or '').upper()
            if 'INSUR' in c_type:
                return 'CGHS CASH'

            return None

        # 2. Fetch live records for the date range
        # OP Registrations
        bills = list(hms_db['hospital_billing'].find({
            '$or': [{'bill_name': 'REGISTRATION'}, {'bill_type': 5}],
            'billed_date': {'$gte': dt_start, '$lte': dt_end}
        }).sort('billed_date', 1))

        # IP Admissions
        adms_cur = list(hms_db['hospital_admission'].find({
            'admissionDateTime': {'$gte': dt_start, '$lte': dt_end}
        }).sort('admissionDateTime', 1))

        # Collect unique UHIDs
        all_uhids = list(set(
            [b.get('uhid') for b in bills if b.get('uhid')] +
            [a.get('uhid') for a in adms_cur if a.get('uhid')]
        ))

        # Batch queries for instant performance (<100ms)
        patients_map = {p['uhid']: p for p in hms_db['hospital_patient'].find({'uhid': {'$in': all_uhids}})}

        adms_hist = defaultdict(list)
        for a in hms_db['hospital_admission'].find({'uhid': {'$in': all_uhids}}).sort('admissionDateTime', -1):
            adms_hist[a['uhid']].append(a)

        claims_hist = defaultdict(list)
        for c in hms_db['hospital_insuranceclaim'].find({'uhid': {'$in': all_uhids}}).sort('claim_date', -1):
            claims_hist[c['uhid']].append(c)

        mems_hist = defaultdict(list)
        for m in hms_db['hospital_insurancemember'].find({'uhid': {'$in': all_uhids}}):
            mems_hist[m['uhid']].append(m)

        visits_hist = defaultdict(list)
        for v in hms_db['hospital_insurancemembervisit'].find({'uhid': {'$in': all_uhids}}).sort('visit_date', -1):
            visits_hist[v['uhid']].append(v)

        grouped_by_date = {}
        seen_ops = set()

        # Process OP registration bills
        for b in bills:
            uhid = b.get('uhid')
            pat = patients_map.get(uhid) or {}
            comp = resolve_company_entry(
                uhid, pat, adms_hist[uhid], claims_hist[uhid], mems_hist[uhid], visits_hist[uhid], bill=b
            )
            if not comp or comp == 'PRIVATE / CASH':
                continue

            if company_filter and company_filter.upper() != 'ALL':
                if company_filter.upper() not in comp.upper():
                    continue

            b_date = b.get('billed_date')
            d_str = b_date.strftime("%d/%m/%Y") if isinstance(b_date, datetime) else str(b_date)[:10]

            if d_str not in grouped_by_date:
                grouped_by_date[d_str] = {}
            if comp not in grouped_by_date[d_str]:
                grouped_by_date[d_str][comp] = []

            pname = b.get('patient_name') or pat.get('name') or ''
            addr = pat.get('permanent_address') or ''
            doc = b.get('doctorName') or pat.get('doctorName') or ''

            grouped_by_date[d_str][comp].append({
                "op_number": uhid or '',
                "patient_name": pname,
                "address": addr,
                "doctor_name": doc,
                "claim_status": ""
            })
            seen_ops.add(uhid)

        # Process Inpatient admissions
        for a in adms_cur:
            uhid = a.get('uhid')
            if uhid in seen_ops:
                continue
            pat = patients_map.get(uhid) or {}
            comp = resolve_company_entry(
                uhid, pat, adms_hist[uhid], claims_hist[uhid], mems_hist[uhid], visits_hist[uhid], adm=a
            )
            if not comp or comp == 'PRIVATE / CASH':
                continue

            if company_filter and company_filter.upper() != 'ALL':
                if company_filter.upper() not in comp.upper():
                    continue

            a_date = a.get('admissionDateTime')
            d_str = a_date.strftime("%d/%m/%Y") if isinstance(a_date, datetime) else str(a_date)[:10]

            if d_str not in grouped_by_date:
                grouped_by_date[d_str] = {}
            if comp not in grouped_by_date[d_str]:
                grouped_by_date[d_str][comp] = []

            pname = pat.get('name') or ''
            addr = pat.get('permanent_address') or ''
            doc = a.get('admittingDoctor') or a.get('consultingDoctor') or ''

            grouped_by_date[d_str][comp].append({
                "op_number": uhid or '',
                "patient_name": pname,
                "address": addr,
                "doctor_name": doc,
                "claim_status": ""
            })
            seen_ops.add(uhid)

        # Build companies list for filter dropdown
        provider_docs = list(hms_db['hospital_insuranceprovider'].find({}, {"company_name": 1, "_id": 0}))
        company_names_set = set([c.get('company_name').strip() for c in provider_docs if c.get('company_name')])
        # Add all companies present in grouped data
        for comps in grouped_by_date.values():
            for c in comps.keys():
                company_names_set.add(c)
        company_names = sorted(list(company_names_set))
        total_pats = sum(sum(len(items) for items in comps.values()) for comps in grouped_by_date.values())

        return Response({
            "success": True,
            "message": "Success" if grouped_by_date else "No record found",
            "report_title": "Company wise registration details",
            "header": {
                "hospital_name": "SHANMUGA HOSPITAL LIMITED",
                "hospital_address": "51/24, Saradha College Road, Salem - 636007"
            },
            "columns": ["OPNUMBER", "PATIENT NAME", "ADDRESS", "DOCTOR NAME"],
            "grouped_data": grouped_by_date,
            "companies": company_names,
            "total_registrations": total_pats
        }, status=status.HTTP_200_OK)
    finally:
        client.close()




# ─────────────────────────────────────────────────────────────────────────────
# 7. INSURANCE DISCHARGE BILL (ALL) API
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def insurance_discharge_bill_all_api(request):
    """
    Returns itemized inpatient discharge voucher statement matching Insurance Discharge Bill (All).pdf.
    Filters: ip_number, uhid.
    NO fallback data: returns empty particulars if patient/bill not found in DB.
    """
    client, hms_db, global_db = get_db()
    try:
        ip_number = request.GET.get('ip_number', '').strip()
        uhid = request.GET.get('uhid', '').strip()
        report_title_param = request.GET.get('report_title', '').strip()
        report_type = request.GET.get('report_type', '').strip().lower()
        title_to_use = report_title_param.upper() if report_title_param else "INSURANCE DISCHARGE BILL (ALL)"

        if not ip_number and not uhid:
            return Response({
                "success": True,
                "message": "No record found",
                "report_title": title_to_use,
                "patient_info": None,
                "bill_meta": {},
                "total_amount": 0.0,
                "bill_particulars": [],
                "bill_details": [],
                "summary": {}
            }, status=status.HTTP_200_OK)

        # 1. Fetch real discharge bill from MongoDB
        dbill = None
        if ip_number:
            dbill = hms_db['hospital_dischargebilling'].find_one({
                "$or": [{"ip_number": ip_number}, {"ipNumber": ip_number}]
            })
        if not dbill and uhid:
            dbill = hms_db['hospital_dischargebilling'].find_one({"uhid": uhid})

        target_ip = dbill.get('ip_number') or dbill.get('ipNumber') if dbill else ip_number
        target_uhid = dbill.get('uhid') if dbill else uhid

        # 2. Fetch Patient & Admission
        pat = hms_db['hospital_patient'].find_one({"uhid": target_uhid}) if target_uhid else None
        adm = None
        if target_ip:
            adm = hms_db['hospital_admission'].find_one({"$or": [{"ipNumber": target_ip}, {"ip_number": target_ip}]})
        if not adm and target_uhid:
            adm = hms_db['hospital_admission'].find_one({"uhid": target_uhid}, sort=[("admissionDateTime", -1)])

        if not dbill and not adm and not pat:
            return Response({
                "success": True,
                "message": "No record found",
                "report_title": "INSURANCE DISCHARGE BILL (ALL)",
                "patient_info": None,
                "bill_meta": {},
                "total_amount": 0.0,
                "bill_particulars": [],
                "bill_details": [],
                "summary": {}
            }, status=status.HTTP_200_OK)

        pname = f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip() if pat else (dbill.get('patient_name') if dbill else (adm.get('patientName') if adm else ''))
        age = (pat.get('age') if pat else None) or (adm.get('age') if adm else '') or ''
        gender = (pat.get('gender') if pat else '') or ''
        age_gender = f"{age} Yrs / {gender}".strip(' /')
        addr = (pat.get('permanent_address') if pat else '') or ''
        doc_name = (pat.get('doctorName') if pat else '') or (adm.get('admittingDoctor') if adm else '') or (adm.get('doctorName') if adm else '')

        # Corporate / TPA company name
        comp_name = (adm.get('insurance_company') if adm else '') or (pat.get('company_name') if pat else '')
        if not comp_name and dbill:
            c = dbill.get('company_name', '')
            if c and c != 'N':
                comp_name = c
        if not comp_name or comp_name == '-':
            if 'railway' in report_type or 'railway' in title_to_use.lower():
                comp_name = 'RAILWAY CTSE'
            else:
                comp_name = '-'

        # Room category
        room_cat = adm.get('roomNumber') if adm else ''
        if not room_cat and adm and adm.get('room_details'):
            r_list = adm.get('room_details')
            if isinstance(r_list, list) and len(r_list) > 0 and isinstance(r_list[0], dict):
                room_cat = r_list[0].get('roomNo') or ''
        if not room_cat and dbill:
            room_cat = dbill.get('room_number') or ''
        if not room_cat:
            room_cat = '-'

        # Bill date
        b_date = dbill.get('bill_date') or dbill.get('created_date') if dbill else None
        b_date_str = b_date.strftime("%d/%m/%Y") if isinstance(b_date, datetime) else (str(b_date or '')[:10] or '-')

        # Admission date (DOA)
        adm_dt = adm.get('admissionDateTime') or adm.get('created_date') if adm else None
        adm_dt_str = adm_dt.strftime("%d/%m/%Y") if isinstance(adm_dt, datetime) else (str(adm_dt or '')[:10] or '-')

        # Discharge date (DOD)
        dis_dt = adm.get('dischargeDateTime') if adm else None
        if not dis_dt and adm and adm.get('room_details'):
            r_list = adm.get('room_details')
            if isinstance(r_list, list) and len(r_list) > 0 and isinstance(r_list[-1], dict):
                end_str = r_list[-1].get('endDateTime')
                if end_str:
                    try:
                        dis_dt = datetime.fromisoformat(end_str.split('+')[0])
                    except Exception:
                        pass
        if not dis_dt and dbill:
            dis_dt = dbill.get('bill_date') or dbill.get('created_date')
        dis_dt_str = dis_dt.strftime("%d/%m/%Y") if isinstance(dis_dt, datetime) else (str(dis_dt or '')[:10] or '-')

        # Days count
        days_count = 1
        try:
            if isinstance(adm_dt, datetime) and isinstance(dis_dt, datetime):
                delta = (dis_dt.date() - adm_dt.date()).days
                days_count = max(1, delta)
        except Exception:
            days_count = 1

        claim_no = (dbill.get('claim_number') if dbill else None) or (dbill.get('claim_intimation_no') if dbill else None) or (adm.get('claim_number') if adm else '') or '-'
        approval_no = (adm.get('approval_number') if adm else None) or (dbill.get('approval_number') if dbill else None) or (dbill.get('preauth_number') if dbill else None) or (dbill.get('remarks') if dbill else None) or '-'
        b_no = str(dbill.get('bill_no', '')) if dbill else '-'

        # Real bill items from dbill if present
        bill_particulars = []
        if dbill:
            particulars_raw = dbill.get('bill_particulars') or dbill.get('items') or []
            if particulars_raw:
                for idx, p in enumerate(particulars_raw):
                    item_amt = clean_num(p.get('amount') if p.get('amount') is not None else (clean_num(p.get('rate')) * clean_num(p.get('quantity', 1))))
                    bill_particulars.append({
                        "slno": idx + 1,
                        "category": p.get('category') or p.get('particulars') or p.get('itemName') or f"Service {idx+1}",
                        "particulars": p.get('particulars') or p.get('itemName') or p.get('category') or f"Service {idx+1}",
                        "units": str(p.get('units') or p.get('quantity') or "1"),
                        "amount": round(item_amt, 2)
                    })
            else:
                # Build real amounts stored on dbill
                sno = 1
                if dbill.get('procedure_amount'):
                    bill_particulars.append({"slno": sno, "category": "Procedure / Treatment Charges", "particulars": "Procedure / Treatment Charges", "units": "1", "amount": round(clean_num(dbill['procedure_amount']), 2)})
                    sno += 1
                if dbill.get('room_rent') or dbill.get('room_charges'):
                    bill_particulars.append({"slno": sno, "category": "Room Rent & Nursing Charges", "particulars": "Room Rent & Nursing Charges", "units": "Days", "amount": round(clean_num(dbill.get('room_rent') or dbill.get('room_charges')), 2)})
                    sno += 1
                if dbill.get('medicines_amount'):
                    bill_particulars.append({"slno": sno, "category": "Medicine Charges (Pharmacy)", "particulars": "Medicine Charges (Pharmacy)", "units": "Items", "amount": round(clean_num(dbill['medicines_amount']), 2)})
                    sno += 1
                if dbill.get('investigation_amount') or dbill.get('lab_amount'):
                    bill_particulars.append({"slno": sno, "category": "Investigation & Lab Charges", "particulars": "Investigation & Lab Charges", "units": "Profiles", "amount": round(clean_num(dbill.get('investigation_amount') or dbill.get('lab_amount')), 2)})
                    sno += 1
                if dbill.get('total_amount') and not bill_particulars:
                    bill_particulars.append({"slno": sno, "category": "Hospital Inpatient Charges", "particulars": "Hospital Inpatient Charges", "units": "1", "amount": round(clean_num(dbill['total_amount']), 2)})

        gross_tot = round(sum(p['amount'] for p in bill_particulars), 2) if bill_particulars else clean_num(dbill.get('total_amount') if dbill else 0.0)
        adv_paid = clean_num(dbill.get('advance_amount') if dbill else 0.0)

        patient_info = {
            "hospital_name": "SHANMUGA HOSPITAL LIMITED",
            "hospital_address": "51/24, Saradha College Road, Salem - 636007",
            "phone": "0427-2706666",
            "fax": "0427-2311891",
            "ip_number": target_ip,
            "op_number": target_uhid,
            "uhid": target_uhid,
            "patient_name": pname,
            "name": pname,
            "age": age,
            "gender": gender,
            "age_gender": age_gender,
            "address": addr,
            "doctor_name": doc_name,
            "doctor": doc_name,
            "claim_intimation_no": claim_no,
            "bill_no": b_no,
            "bill_number": b_no,
            "bill_date": b_date_str,
            "doa": adm_dt_str,
            "dod": dis_dt_str,
            "admitted_date": adm_dt_str,
            "discharge_date": dis_dt_str,
            "room_category": room_cat,
            "room": room_cat,
            "company_name": comp_name,
            "insurance_company": comp_name,
            "company": comp_name,
            "days": days_count,
            "total_days": days_count,
            "approval": approval_no,
            "preauth_amount": clean_num(dbill.get('preauth_amount', 0.0) if dbill else 0.0)
        }

        bill_meta = {
            "bill_number": b_no,
            "bill_no": b_no,
            "bill_date": b_date_str,
            "doa": adm_dt_str,
            "dod": dis_dt_str,
            "room": room_cat,
            "room_category": room_cat,
            "days": days_count,
            "total_days": days_count,
            "company": comp_name,
            "company_name": comp_name,
            "approval": approval_no
        }

        return Response({
            "success": True,
            "message": "Success" if bill_particulars else "No record found",
            "report_title": title_to_use,
            "patient_info": patient_info,
            "bill_meta": bill_meta,
            "total_amount": round(gross_tot, 2),
            "bill_particulars": bill_particulars,
            "bill_details": bill_particulars,
            "summary": {
                "gross_bill_amount": round(gross_tot, 2),
                "advance_copay_paid": round(adv_paid, 2),
                "net_insurance_claim": round(gross_tot - adv_paid, 2)
            }
        }, status=status.HTTP_200_OK)
    finally:
        client.close()




# ─────────────────────────────────────────────────────────────────────────────
# 8. PRESCRIPTION DETAILS API
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def prescription_details_api(request):
    """
    Returns Doctor prescription medication slip matching Prescription Details.pdf.
    Filters: uhid, from_date, to_date.
    NO fallback data: returns empty list if no prescriptions exist in DB.
    """
    client, hms_db, global_db = get_db()
    try:
        uhid = request.GET.get('uhid', '').strip()
        from_date_str = request.GET.get('from_date') or request.GET.get('start_date')
        to_date_str = request.GET.get('to_date') or request.GET.get('end_date')

        if not uhid:
            return Response({
                "success": True,
                "message": "No record found",
                "report_title": "PRESCRIPTION DETAILS",
                "patient_info": None,
                "prescriptions": [],
                "summary": {}
            }, status=status.HTTP_200_OK)

        pat = hms_db['hospital_patient'].find_one({
            "$or": [{"uhid": uhid}, {"uhid": re.compile(f"^{re.escape(uhid)}$", re.IGNORECASE)}]
        })
        if not pat:
            return Response({
                "success": True,
                "message": "No record found",
                "report_title": "PRESCRIPTION DETAILS",
                "patient_info": None,
                "prescriptions": [],
                "summary": {}
            }, status=status.HTTP_200_OK)

        target_uhid = pat.get('uhid', uhid)
        pname = f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip() or pat.get('patientName', '')
        doc_name = pat.get('doctorName', '')

        adm = hms_db['hospital_admission'].find_one({"uhid": target_uhid}) or {}
        ip_no = adm.get('ipNumber', '')
        room_no = adm.get('roomNumber', '')

        # Fetch prescribed drugs from pharmacy billing or emr for this patient
        pharm_bills = list(hms_db['hospital_pharmacybilling'].find({"uhid": target_uhid}))
        prescriptions = []

        if pharm_bills:
            for b in pharm_bills:
                b_date = b.get('bill_date') or b.get('created_date')
                b_date_str = b_date.strftime("%d/%m/%Y") if isinstance(b_date, datetime) else str(b_date)[:10]

                items = []
                for idx, it in enumerate(b.get('medicine_particulars') or b.get('items') or []):
                    items.append({
                        "sl_no": idx + 1,
                        "item_name": it.get('item_name') or it.get('name') or f"MEDICINE {idx+1}",
                        "qty": int(clean_num(it.get('qty') or it.get('quantity') or 1))
                    })

                if items:
                    prescriptions.append({
                        "prescription_date": b_date_str,
                        "doctor_name": b.get('doctor_name') or doc_name,
                        "department": b.get('department', 'GENERAL MEDICINE'),
                        "items": items
                    })

        patient_info = {
            "patient_name": pname,
            "uhid": target_uhid,
            "op_number": target_uhid,
            "ip_number": ip_no,
            "room_no": room_no,
            "doctor_name": doc_name
        }

        return Response({
            "success": True,
            "message": "Success" if prescriptions else "No record found",
            "report_title": "PRESCRIPTION DETAILS",
            "patient_info": patient_info,
            "prescriptions": prescriptions,
            "summary": {
                "total_prescriptions": len(prescriptions),
                "total_items": sum(len(p['items']) for p in prescriptions)
            }
        }, status=status.HTTP_200_OK)
    finally:
        client.close()


# ─────────────────────────────────────────────────────────────────────────────
# 9. MEDICINE ABSTRACT REPORT API
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def medicine_abstract_api(request):
    """
    Returns summarized IP medicine bills for a patient matching Medicine Abstract Report.pdf.
    Filters: ip_number, uhid, from_date, to_date.
    Columns: Slno, Bill Date, Bill Number, Credit Status, Taxable Amt, Cgst, Sgst, Gst, Bill Amount
    """
    client, hms_db, global_db = get_db()
    try:
        search_ip = (request.GET.get('ip_number') or request.GET.get('ip_no') or '').strip()
        search_uhid = (request.GET.get('uhid') or '').strip()
        from_date_str = request.GET.get('from_date') or request.GET.get('start_date')
        to_date_str = request.GET.get('to_date') or request.GET.get('end_date')

        search_term = search_ip or search_uhid
        if not search_term:
            return Response({
                "success": True,
                "message": "No record found",
                "hospital_name": "SHANMUGA HOSPITAL LIMITED",
                "hospital_address": "51/24, Saradha College Road, Salem - 636007",
                "hospital_phone": "04272706666",
                "report_title": "Medicine Abstract Report",
                "patient_info": None,
                "bills": [],
                "summary": {}
            }, status=status.HTTP_200_OK)

        dt_start = parse_date(from_date_str)
        dt_end = parse_date(to_date_str, is_end=True)

        # 1. Resolve Admission & Patient Info
        adm_doc = hms_db['hospital_admission'].find_one(
            {"$or": [
                {"ipNumber": search_term},
                {"ipNumber": re.compile(f"^{re.escape(search_term)}$", re.IGNORECASE)},
                {"uhid": search_term},
                {"uhid": re.compile(f"^{re.escape(search_term)}$", re.IGNORECASE)}
            ]},
            sort=[("admissionDateTime", -1)]
        )

        target_ip = (adm_doc.get('ipNumber') if adm_doc else search_ip) or search_term
        target_uhid = (adm_doc.get('uhid') if adm_doc else search_uhid) or search_term

        all_adms = list(hms_db['hospital_admission'].find({"$or": [
            {"uhid": target_uhid},
            {"uhid": target_ip},
            {"ipNumber": target_ip},
            {"ipNumber": target_uhid}
        ]}))
        all_ips = {a.get('ipNumber') for a in all_adms if a.get('ipNumber')}
        all_ips.add(target_ip)
        all_uhids = {a.get('uhid') for a in all_adms if a.get('uhid')}
        all_uhids.add(target_uhid)

        patient_doc = hms_db['hospital_patient'].find_one({"uhid": target_uhid})
        if not patient_doc:
            patient_doc = hms_db['hospital_patient'].find_one({"uhid": target_ip})

        patient_name = f"{patient_doc.get('firstName', '')} {patient_doc.get('lastName', '')}".strip() if patient_doc else (adm_doc.get('patientName', '') if adm_doc else '')

        # 2. Ward requests dispatches for this patient across admissions
        wr_or = []
        for u in all_uhids:
            wr_or.append({"uhid": u})
            wr_or.append({"inpatient_number": u})
        for ip in all_ips:
            wr_or.append({"uhid": ip})
            wr_or.append({"inpatient_number": ip})

        wr_docs = list(hms_db['hospital_pharmacybilling'].find({
            "$or": wr_or,
            "is_ward_request": True
        }))

        wr_dispatch_map = {}
        dispatch_dates = {}
        for wr in wr_docs:
            for dh in (wr.get('dispatch_history') or []):
                bno = dh.get('bill_no')
                if bno:
                    item_ids = {it.get('item_id') for it in (dh.get('items') or []) if it.get('item_id')}
                    if bno in wr_dispatch_map:
                        wr_dispatch_map[bno].update(item_ids)
                    else:
                        wr_dispatch_map[bno] = item_ids
                    ts = dh.get('timestamp')
                    if ts and bno not in dispatch_dates:
                        try:
                            dispatch_dates[bno] = datetime.fromisoformat(ts[:19])
                        except Exception:
                            pass

        # 3. Query all candidate bills
        bill_query_or = []
        for u in all_uhids:
            bill_query_or.append({"uhid": u})
        for ip in all_ips:
            bill_query_or.append({"uhid": ip})
            bill_query_or.append({"inpatient_number": ip})
        if wr_dispatch_map:
            bill_query_or.append({"bill_no": {"$in": list(wr_dispatch_map.keys())}})
        if patient_name:
            bill_query_or.append({"patient_name": patient_name})
            bill_query_or.append({"patientname": patient_name})

        raw_bills = list(hms_db['hospital_pharmacybilling'].find({
            "$or": bill_query_or,
            "is_ward_request": {"$ne": True}
        }).sort("created_date", 1))

        # Helper to process bills with date filter
        def collect_bills(apply_dates=True):
            seen_bids = set()
            out_bills = []
            for b in raw_bills:
                b_no = b.get('bill_no')
                if not b_no or b_no in seen_bids:
                    continue

                b_mode = str(b.get('billing_mode') or '').upper()
                b_type = b.get('bill_type')
                b_pmode = str(b.get('payment_mode') or '').upper()
                
                # Exclude purely counter direct cash/UPI sales unless IP credit or part of patient's IP ledger
                if b_pmode in ('CASH', 'UPI') and 'IP' not in b_mode and b_no not in wr_dispatch_map:
                    continue

                # Must be IP credit or linked to patient's admission / ward requests
                if not (b_no in wr_dispatch_map or 'IP' in b_mode or b_type == 18 or (patient_name and b.get('patient_name') == patient_name)):
                    continue

                # Determine bill date
                b_dt = dispatch_dates.get(b_no)
                if not b_dt:
                    raw_date = b.get('bill_date') or b.get('created_date')
                    if isinstance(raw_date, datetime):
                        b_dt = raw_date
                    elif isinstance(raw_date, str):
                        try:
                            b_dt = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                        except Exception:
                            b_dt = parse_date(raw_date[:10])

                if apply_dates and dt_start and b_dt:
                    b_date_only = b_dt.date() if hasattr(b_dt, 'date') else b_dt
                    s_date_only = dt_start.date() if hasattr(dt_start, 'date') else dt_start
                    e_date_only = dt_end.date() if hasattr(dt_end, 'date') else dt_end
                    if not (s_date_only <= b_date_only <= e_date_only):
                        continue

                b_date_str = b_dt.strftime("%d/%m/%Y") if b_dt else ""

                allowed_ids = wr_dispatch_map.get(b_no)
                items = b.get('medicine_particulars') or b.get('items') or []

                b_taxable = 0.0
                for itm in items:
                    it_id = itm.get('item_id')
                    if allowed_ids and it_id not in allowed_ids:
                        continue
                    calc_price = clean_num(itm.get('calculated_price') or (clean_num(itm.get('price')) * clean_num(itm.get('qty', 1))))
                    b_taxable += calc_price

                if b_taxable <= 0:
                    continue

                seen_bids.add(b_no)

                # Standard 5% GST on pharmacy medicines (2.5% CGST + 2.5% SGST)
                gst = round(b_taxable * 0.05, 2)
                cgst = round(gst / 2.0, 2)
                sgst = round(gst / 2.0, 2)
                bill_amt = round(b_taxable + gst, 2)

                naive_dt = b_dt.replace(tzinfo=None) if (b_dt and hasattr(b_dt, 'tzinfo') and b_dt.tzinfo is not None) else (b_dt or datetime.min)
                out_bills.append({
                    "bill_date": b_date_str,
                    "bill_number": b_no,
                    "credit_status": "IP CREDITS",
                    "taxable_amt": round(b_taxable, 2),
                    "cgst": cgst,
                    "sgst": sgst,
                    "gst": gst,
                    "bill_amount": bill_amt,
                    "sort_key": naive_dt
                })

            out_bills.sort(key=lambda x: (x["sort_key"], x["bill_number"]))
            for idx, ob in enumerate(out_bills, 1):
                ob["sl_no"] = idx
                del ob["sort_key"]
            return out_bills

        bills = collect_bills(apply_dates=True)
        if not bills and (dt_start or dt_end):
            bills = collect_bills(apply_dates=False)

        total_taxable = round(sum(b['taxable_amt'] for b in bills), 2)
        total_cgst = round(sum(b['cgst'] for b in bills), 2)
        total_sgst = round(sum(b['sgst'] for b in bills), 2)
        total_gst = round(sum(b['gst'] for b in bills), 2)
        total_bill_amount = round(sum(b['bill_amount'] for b in bills), 2)

        return Response({
            "success": True,
            "message": "Success" if bills else "No record found",
            "hospital_name": "SHANMUGA HOSPITAL LIMITED",
            "hospital_address": "51/24, Saradha College Road, Salem - 636007",
            "hospital_phone": "04272706666",
            "report_title": "Medicine Abstract Report",
            "patient_info": {
                "patient_name": patient_name,
                "ip_number": target_ip,
                "op_number": target_uhid
            },
            "bills": bills,
            "summary": {
                "total_taxable": total_taxable,
                "total_cgst": total_cgst,
                "total_sgst": total_sgst,
                "total_gst": total_gst,
                "total_bill_amount": total_bill_amount
            }
        }, status=status.HTTP_200_OK)
    finally:
        client.close()




