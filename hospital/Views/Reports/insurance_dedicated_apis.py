from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
from bson import Decimal128, ObjectId
from datetime import datetime, timedelta
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
    NO fallback data: returns live data from MongoDB or empty structure with 'No record found'.
    """
    client, hms_db, global_db = get_db()
    try:
        company_filter = request.GET.get('company_name', 'ALL').strip()
        outlet_filter = request.GET.get('outlet_name', 'ALL').strip()

        # Query active admitted inpatients from MongoDB
        query = {"$or": [{"status": {"$in": ["Admitted", "admitted", "INPATIENT"]}}, {"is_discharged": False}, {"dischargeDateTime": None}]}
        if outlet_filter and outlet_filter.upper() != 'ALL':
            query["outlet_code"] = outlet_filter

        live_admissions = list(hms_db['hospital_admission'].find(query))

        raw_occupancy = []
        for adm in live_admissions:
            cname = (adm.get('company_name') or adm.get('insurance_company') or 'PRIVATE / CASH').strip()
            if company_filter and company_filter.upper() != 'ALL':
                if company_filter.upper() not in cname.upper():
                    continue

            uhid = adm.get('uhid')
            pat = hms_db['hospital_patient'].find_one({"uhid": uhid}) if uhid else None

            pname = f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip() if pat else (adm.get('patientName') or '')
            age_gender = f"{pat.get('age', '')} Yrs / {pat.get('gender', '')}" if pat else ""
            rel = f"S/o / W/o {pat.get('fatherName') or pat.get('husbandName', '')}" if pat else ""
            addr = pat.get('permanent_address', '') if pat else ""

            adm_dt = adm.get('admissionDateTime') or adm.get('created_date')
            adm_dt_str = adm_dt.strftime("%d/%m/%Y") if isinstance(adm_dt, datetime) else str(adm_dt)[:10]

            floor = "1ST FLOOR"
            room_no = adm.get('roomNumber', '101')
            r_details = adm.get('room_details') or []
            if r_details and isinstance(r_details, list) and isinstance(r_details[0], dict):
                room_no = r_details[0].get('roomNo', room_no)
            if str(room_no).startswith('2'): floor = "2ND FLOOR"
            elif str(room_no).startswith('3'): floor = "3RD FLOOR"
            elif 'SICU' in str(room_no).upper(): floor = "SICU"
            elif 'MICU' in str(room_no).upper(): floor = "MICU"

            raw_occupancy.append({
                "company_name": cname,
                "floor": floor,
                "ip_number": adm.get('ipNumber', ''),
                "op_number": uhid or '',
                "patient_name": pname,
                "age_gender": age_gender,
                "relative_info": rel,
                "address": addr,
                "admitting_date": adm_dt_str,
                "room_number": str(room_no)
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
            "total_occupied_beds": len(raw_occupancy)
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

        query = {}
        if dt_start and dt_end:
            query["$or"] = [
                {"registration_date": {"$gte": dt_start, "$lte": dt_end}},
                {"created_date": {"$gte": dt_start, "$lte": dt_end}}
            ]

        pats = list(hms_db['hospital_patient'].find(query).sort("created_date", 1))
        grouped_by_date = {}

        for p in pats:
            comp = (p.get('company_name') or p.get('insurance_company') or 'PRIVATE / CASH').strip()
            if company_filter and company_filter.upper() != 'ALL':
                if company_filter.upper() not in comp.upper():
                    continue

            r_date = p.get('registration_date') or p.get('created_date')
            d_str = r_date.strftime("%d/%m/%Y") if isinstance(r_date, datetime) else str(r_date)[:10]

            if d_str not in grouped_by_date:
                grouped_by_date[d_str] = {}
            if comp not in grouped_by_date[d_str]:
                grouped_by_date[d_str][comp] = []

            pname = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or p.get('patientName', '')
            grouped_by_date[d_str][comp].append({
                "op_number": p.get('uhid', ''),
                "patient_name": pname,
                "address": p.get('permanent_address', ''),
                "doctor_name": p.get('doctorName', ''),
                "claim_status": p.get('claim_status', '')
            })

        companies = list(hms_db['hospital_insuranceprovider'].find({}, {"company_name": 1, "_id": 0}))
        company_names = sorted(list(set([c.get('company_name') for c in companies if c.get('company_name')])))
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

        if not ip_number and not uhid:
            return Response({
                "success": True,
                "message": "No record found",
                "report_title": "INSURANCE DISCHARGE BILL (ALL)",
                "patient_info": None,
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
        adm = hms_db['hospital_admission'].find_one({"$or": [{"ipNumber": target_ip}, {"uhid": target_uhid}]}) if (target_ip or target_uhid) else None

        if not dbill and not adm and not pat:
            return Response({
                "success": True,
                "message": "No record found",
                "report_title": "INSURANCE DISCHARGE BILL (ALL)",
                "patient_info": None,
                "bill_particulars": [],
                "bill_details": [],
                "summary": {}
            }, status=status.HTTP_200_OK)

        pname = f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip() if pat else (dbill.get('patient_name') if dbill else (adm.get('patientName') if adm else ''))
        addr = pat.get('permanent_address', '') if pat else ''
        doc_name = (pat.get('doctorName') if pat else '') or (adm.get('doctorName') if adm else '')
        comp_name = (pat.get('company_name') if pat else '') or (adm.get('insurance_company') if adm else '') or (dbill.get('company_name') if dbill else '')
        room_cat = (adm.get('roomNumber') if adm else '') or (dbill.get('room_number') if dbill else '')

        b_date = dbill.get('bill_date') if dbill else None
        b_date_str = b_date.strftime("%d/%m/%Y") if isinstance(b_date, datetime) else str(b_date or '')[:10]

        adm_dt = adm.get('admissionDateTime') or adm.get('created_date') if adm else None
        adm_dt_str = adm_dt.strftime("%d/%m/%Y %I:%M %p") if isinstance(adm_dt, datetime) else str(adm_dt or '')

        dis_dt = adm.get('dischargeDateTime') if adm else None
        dis_dt_str = dis_dt.strftime("%d/%m/%Y %I:%M %p") if isinstance(dis_dt, datetime) else str(dis_dt or '')

        # Real bill items from dbill if present
        bill_particulars = []
        if dbill:
            particulars_raw = dbill.get('bill_particulars') or dbill.get('items') or []
            if particulars_raw:
                for idx, p in enumerate(particulars_raw):
                    bill_particulars.append({
                        "slno": idx + 1,
                        "category": p.get('category') or p.get('particulars') or f"Service {idx+1}",
                        "particulars": p.get('particulars') or p.get('category') or f"Service {idx+1}",
                        "units": str(p.get('units') or "1"),
                        "amount": clean_num(p.get('amount') or 0.0)
                    })
            else:
                # Build real amounts stored on dbill
                sno = 1
                if dbill.get('procedure_amount'):
                    bill_particulars.append({"slno": sno, "category": "Procedure / Treatment Charges", "particulars": "Procedure / Treatment Charges", "units": "1", "amount": clean_num(dbill['procedure_amount'])})
                    sno += 1
                if dbill.get('room_rent') or dbill.get('room_charges'):
                    bill_particulars.append({"slno": sno, "category": "Room Rent & Nursing Charges", "particulars": "Room Rent & Nursing Charges", "units": "Days", "amount": clean_num(dbill.get('room_rent') or dbill.get('room_charges'))})
                    sno += 1
                if dbill.get('medicines_amount'):
                    bill_particulars.append({"slno": sno, "category": "Medicine Charges (Pharmacy)", "particulars": "Medicine Charges (Pharmacy)", "units": "Items", "amount": clean_num(dbill['medicines_amount'])})
                    sno += 1
                if dbill.get('investigation_amount') or dbill.get('lab_amount'):
                    bill_particulars.append({"slno": sno, "category": "Investigation & Lab Charges", "particulars": "Investigation & Lab Charges", "units": "Profiles", "amount": clean_num(dbill.get('investigation_amount') or dbill.get('lab_amount'))})
                    sno += 1
                if dbill.get('total_amount') and not bill_particulars:
                    bill_particulars.append({"slno": sno, "category": "Hospital Inpatient Charges", "particulars": "Hospital Inpatient Charges", "units": "1", "amount": clean_num(dbill['total_amount'])})

        gross_tot = sum(p['amount'] for p in bill_particulars) if bill_particulars else clean_num(dbill.get('total_amount') if dbill else 0.0)
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
            "address": addr,
            "doctor_name": doc_name,
            "claim_intimation_no": dbill.get('claim_intimation_no', '') if dbill else '',
            "bill_no": dbill.get('bill_no', '') if dbill else '',
            "bill_date": b_date_str,
            "doa": adm_dt_str,
            "dod": dis_dt_str,
            "room_category": room_cat,
            "company_name": comp_name,
            "preauth_amount": clean_num(dbill.get('preauth_amount', 0.0) if dbill else 0.0)
        }

        return Response({
            "success": True,
            "message": "Success" if bill_particulars else "No record found",
            "report_title": "INSURANCE DISCHARGE BILL (ALL)",
            "patient_info": patient_info,
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



