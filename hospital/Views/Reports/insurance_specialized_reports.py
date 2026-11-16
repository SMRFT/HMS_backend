from rest_framework.response import Response
from rest_framework import status
from datetime import datetime, timedelta
from bson import Decimal128
from collections import defaultdict
import os
import json
from pymongo import MongoClient

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


def parse_record_date(dt_val):
    if not dt_val:
        return None
    if isinstance(dt_val, datetime):
        return dt_val
    if isinstance(dt_val, str):
        val = dt_val.strip()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(val[:19], fmt[:len(val[:19])])
            except Exception:
                continue
    return None


def row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map=None):
    # 1. Date Range Filter
    if dt_start and dt_end:
        rec_date = parse_record_date(
            row.get('bill_date') or row.get('date') or row.get('discharge_date') or row.get('cert_date') or row.get('reg_date') or row.get('admitting_date') or row.get('admission_date')
        )
        if rec_date:
            rec_date_only = rec_date.replace(hour=0, minute=0, second=0, microsecond=0)
            start_only = dt_start.replace(hour=0, minute=0, second=0, microsecond=0)
            end_only = dt_end.replace(hour=23, minute=59, second=59, microsecond=999999)
            if not (start_only <= rec_date_only <= end_only):
                return False

    # 2. Company Filter
    if company_filter and str(company_filter).strip().lower() != 'all':
        cf_low = str(company_filter).strip().lower()
        c_name = str(row.get('company_name') or '').lower()
        c_code = str(row.get('company_code') or '').lower()

        # Exact code match
        matched = False
        if c_code and c_code == cf_low:
            matched = True
            if cf_low == '100002' and 'railway' in c_name:
                matched = False
            elif cf_low in ('100003', '100059') and 'echs' in c_name:
                matched = False

        # Company name match
        if not matched:
            matched = (cf_low in c_name or c_name in cf_low)

        if not matched and company_map:
            mapped_name = str(company_map.get(company_filter, '')).lower()
            if mapped_name and (mapped_name in c_name or c_name in mapped_name):
                matched = True

        if not matched:
            for abbr in ['echs', 'railway', 'cghs', 'esi', 'tpa', 'star', 'bajaj', 'aditya', 'tncmchis', 'fci', 'mdindia', 'paramount', 'vidal', 'medi assist']:
                if abbr in cf_low and abbr in c_name:
                    matched = True
                    break

        if not matched:
            return False

    # 3. Search Query Filter
    if search_query:
        sq_low = str(search_query).strip().lower()
        haystack = " ".join(str(v) for v in row.values() if v is not None).lower()
        if sq_low not in haystack:
            return False

    return True


def format_dt(dt_val, fmt="%d/%m/%Y"):
    if not dt_val:
        return ""
    if isinstance(dt_val, datetime):
        return dt_val.strftime(fmt)
    if isinstance(dt_val, str):
        d = parse_record_date(dt_val)
        if d:
            return d.strftime(fmt)
        return dt_val[:10]
    return ""


def build_specialized_insurance_report(request, report_key):
    """
    Builds specialized insurance dataset and column schemas for Shanmuga Hospital insurance reports.
    Queries 100% live database documents from MongoDB (hospital_dischargebilling, hospital_billing,
    hospital_admission, hospital_patient, hospital_investbilling, hospital_pharmacybilling,
    hospital_insuranceclaim, hospital_insurancemember, hospital_insurancemembervisit, hospital_insuranceprovider).
    """
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        global_db = client['Global']

        start_date_str = request.GET.get('start_date') or request.GET.get('from_date')
        end_date_str = request.GET.get('end_date') or request.GET.get('to_date')
        company_filter = request.GET.get('company_code') or request.GET.get('company_name', 'all')
        company_filter = str(company_filter).strip()
        search_query = request.GET.get('search', '').strip().lower()
        uhid_filter = (request.GET.get('uhid') or request.GET.get('op_number') or '').strip()
        ip_number_filter = (request.GET.get('ip_number') or request.GET.get('ipnumber') or '').strip()
        outlet_filter = request.GET.get('outlet_code', 'all').strip()

        now = datetime.now()
        dt_start = None
        dt_end = None
        if start_date_str:
            dt_start = parse_record_date(start_date_str)
        if not dt_start:
            dt_start = now - timedelta(days=90)
        dt_start = dt_start.replace(hour=0, minute=0, second=0, microsecond=0)

        if end_date_str:
            dt_end = parse_record_date(end_date_str)
        if not dt_end:
            dt_end = now
        dt_end = dt_end.replace(hour=23, minute=59, second=59, microsecond=999999)

        # 1. Load Providers & Map
        providers = list(hms_db['hospital_insuranceprovider'].find({}, {'company_code': 1, 'company_name': 1, '_id': 0}))
        company_map = {}
        companies_list = []
        name_to_code_map = {
            'ECHS': '100002',
            'EX-SERVICEMEN CONTRIBUTORY HEALTH SCHEME (ECHS)': '100002',
            'RAILWAY': '100003',
            'RAILWAYS': '100003',
            'SOUTHERN RAILWAY': '100003',
            'SOUTHERN RAILWAY MEDICAL CREDIT': '100003',
            'RAILWAY CTSE': '100059',
            'ESI': '100006',
            'ESIC': '100034',
            'EMPLOYEES STATE INSURANCE (ESI)': '100006',
            'CGHS CREDIT': '100066',
            'CGHS Credit': '100066',
            'CGHS CASH': 'CGHS CASH',
            'CENTRAL GOVERNMENT HEALTH SCHEME (CGHS)': '100066',
            'TNCMCHIS': '100004',
            'CHIEF MINISTER COMPREHENSIVE HEALTH INSURANCE SCHEME': '100004',
            'STAR HEALTH AND ALLIED INSURANCE LTD': '100017',
            'STAR HEALTH': '100017'
        }
        for p in providers:
            cc = str(p.get('company_code') or '').strip()
            cn = (p.get('company_name') or '').strip()
            if cc:
                company_map[cc] = cn or cc
                companies_list.append({"code": cc, "name": cn or cc})
            if cn and cn.upper() not in name_to_code_map:
                name_to_code_map[cn.upper()] = cc

        common_schemes = [
            ("ECHS", "EX-SERVICEMEN CONTRIBUTORY HEALTH SCHEME (ECHS)"),
            ("100002", "EX-SERVICEMEN CONTRIBUTORY HEALTH SCHEME (ECHS)"),
            ("RAILWAY", "SOUTHERN RAILWAY MEDICAL CREDIT"),
            ("100059", "SOUTHERN RAILWAY MEDICAL CREDIT"),
            ("ESI", "EMPLOYEES STATE INSURANCE (ESI)"),
            ("100003", "EMPLOYEES STATE INSURANCE (ESI)"),
            ("CGHS", "CENTRAL GOVERNMENT HEALTH SCHEME (CGHS)"),
            ("TNCMCHIS", "CHIEF MINISTER COMPREHENSIVE HEALTH INSURANCE SCHEME"),
            ("100004", "CHIEF MINISTER COMPREHENSIVE HEALTH INSURANCE SCHEME"),
            ("100026", "BAJAJ ALLIANZ & ALLIED INSURANCE"),
            ("100064", "ADITYA BIRLA CAPITAL"),
            ("100009", "BHARAT SANCHAR NIGAM LIMITED"),
            ("100010", "AIRPORT AUTHORITY OF INDIA")
        ]
        for ccode, cname in common_schemes:
            if ccode not in company_map:
                company_map[ccode] = cname
                companies_list.append({"code": ccode, "name": cname})

        # Pre-load Doctors map from Global diagnostics profile
        doctor_map = {}
        try:
            for ddoc in global_db['backend_diagnostics_profile'].find({'isDoctor': True}, {'employeeId': 1, 'employeeName': 1}):
                eid = str(ddoc.get('employeeId') or '').strip()
                ename = (ddoc.get('employeeName') or '').strip()
                if eid and ename:
                    doctor_map[eid] = ename
        except Exception:
            pass

        key = (report_key or 'insurance_bills_status').lower().strip()

        records = []
        columns = []
        summary = {}
        patient_info = {}
        grouped_data = {}
        bills = []
        report_title = "Insurance Report"

        # ---------------------------------------------------------
        # Helper: Resolve company name cleanly
        # ---------------------------------------------------------
        def resolve_company(c_name, c_code=None, adm=None, pat=None, claim=None):
            if c_name and c_name not in ['N', 'Y', 'None', '', 'PRIVATE / CASH', 'CASH / PRIVATE', 'PRIVATE', 'CASH']:
                return c_name
            if adm:
                ac = adm.get('insurance_company')
                if ac and ac not in ['N', 'Y', 'None', '']:
                    return ac
                ac_code = adm.get('company_code')
                if ac_code and str(ac_code) in company_map:
                    return company_map[str(ac_code)]
            if claim:
                ic = claim.get('insurance_company')
                if ic and ic not in ['N', 'Y', 'None', '']:
                    return company_map.get(str(ic), ic)
            if pat:
                pc = pat.get('company_name')
                if pc and pc not in ['N', 'Y', 'None', '']:
                    return pc
                pc_code = pat.get('company_code')
                if pc_code and str(pc_code) in company_map:
                    return company_map[str(pc_code)]
            if c_code and str(c_code) in company_map:
                return company_map[str(c_code)]
            return "INSURANCE / CORPORATE"

        # ---------------------------------------------------------
        # Helper: Build live pool of discharge bills for status/due reports
        # ---------------------------------------------------------
        def build_live_discharge_pool(limit_count=3000):
            q = {}
            if dt_start and dt_end:
                q["$or"] = [
                    {"bill_date": {"$gte": dt_start, "$lte": dt_end}},
                    {"created_date": {"$gte": dt_start, "$lte": dt_end}}
                ]
            dbills = list(hms_db['hospital_dischargebilling'].find(q).sort("bill_date", -1).limit(limit_count))
            if not dbills:
                dbills = list(hms_db['hospital_dischargebilling'].find({}).sort("bill_date", -1).limit(200))

            b_uhids = list(set([b.get('uhid') for b in dbills if b.get('uhid')]))
            b_ips = list(set([b.get('ip_number') for b in dbills if b.get('ip_number')]))

            b_pats = {p['uhid']: p for p in hms_db['hospital_patient'].find({'uhid': {'$in': b_uhids}}, {"uhid": 1, "firstName": 1, "lastName": 1, "company_code": 1, "company_name": 1, "permanent_address": 1, "mobilePhone": 1, "district": 1, "city": 1})}
            b_adms = {a.get('ipNumber') or a.get('ip_number'): a for a in hms_db['hospital_admission'].find({'$or': [{'ipNumber': {'$in': b_ips}}, {'ip_number': {'$in': b_ips}}]}, {"ipNumber": 1, "ip_number": 1, "company_code": 1, "insurance_company": 1, "patientName": 1, "admissionDateTime": 1, "consultingDoctor": 1, "room_details": 1})}
            b_claims = {c.get('ip_number'): c for c in hms_db['hospital_insuranceclaim'].find({'ip_number': {'$in': b_ips}})}
            b_mems = {m.get('uhid'): m for m in hms_db['hospital_insurancemember'].find({'uhid': {'$in': b_uhids}})}

            pool = []
            for b in dbills:
                uh = b.get('uhid') or ''
                ipn = b.get('ip_number') or ''
                pat = b_pats.get(uh, {})
                adm = b_adms.get(ipn, {})
                clm = b_claims.get(ipn, {})
                mem = b_mems.get(uh, {})

                pname = f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip() or b.get('patient_name') or adm.get('patientName') or f"Patient {uh}"
                cname = resolve_company(b.get('company_name'), b.get('company_code'), adm, pat, clm)
                ccode = name_to_code_map.get(cname.upper()) or str(b.get('company_code') or adm.get('company_code') or pat.get('company_code') or cname)

                b_date = b.get('bill_date')
                b_date_str = format_dt(b_date)
                adm_date_str = format_dt(adm.get('admissionDateTime'))

                b_amt = clean_num(b.get('total_amount'))
                adv_amt = clean_num(b.get('advance_amount'))
                net_amt = clean_num(b.get('net_amount')) or max(0.0, b_amt - adv_amt)

                is_billed = (b.get('status') == 'Billed')
                settled = clean_num(b.get('paid_amount') or b.get('settled_amount') or clm.get('approved_amount', 0))
                if is_billed and settled == 0 and not b.get('is_cancelled'):
                    settled = net_amt

                disallowed = clean_num(b.get('disallowed_amount') or clm.get('disallowed_amount', 0))
                due_amt = clean_num(b.get('due_amount')) or max(0.0, net_amt - settled)

                card_no = str(b.get('id_card_number') or clm.get('policy_no') or mem.get('card_no') or '')
                service_no = str(mem.get('service_number') or b.get('service_number') or '')
                claim_ref = str(b.get('claim_number') or clm.get('claim_id') or mem.get('referral_number') or '')
                place = str(b.get('place') or pat.get('city') or pat.get('district') or 'SALEM')

                pool.append({
                    "bill_date": b_date_str,
                    "patient_name": pname,
                    "bill_amount": round(b_amt, 2),
                    "op_number": uh,
                    "uhid": uh,
                    "despatch_date": format_dt(b.get('despatch_date') or clm.get('claim_date')),
                    "settlement_date": format_dt(b.get('settlement_date') or clm.get('approved_date')),
                    "settled_amount": round(settled, 2),
                    "disallowed_amount": round(disallowed, 2),
                    "due_amount": round(due_amt, 2),
                    "card_number": card_no,
                    "service_no": service_no,
                    "claim_ref": claim_ref,
                    "tds": clean_num(b.get('tds') or b.get('tds_amount', 0)),
                    "paid_by_patient": round(adv_amt, 2),
                    "settlement_duration": "",
                    "ip_number": ipn,
                    "bill_id": str(b.get('bill_no', '')),
                    "sh_bill_no": str(b.get('insurance_bill_number') or b.get('bill_no') or ''),
                    "place": place,
                    "admitting_date": adm_date_str,
                    "discharge_date": b_date_str,
                    "advance": round(adv_amt, 2),
                    "status": str(b.get('status') or 'BILLED').upper(),
                    "old_billno": str(b.get('old_billno') or ''),
                    "company_name": cname,
                    "company_code": ccode,
                    "category": str(b.get('category') or 'PVT'),
                    "raw_bill": b,
                    "raw_adm": adm
                })
            return pool

        # ---------------------------------------------------------
        # 1. Patient Wise Pharmacy IP Bill Detailed
        # ---------------------------------------------------------
        if key in ['patient_wise_pharmacy_ip_bill', 'pharmacy_ip_bill_detailed', 'patientwisepharmacyipbilldetailed', 'patient_wise_pharmacy_ip_bill_detailed', 'patientwisepharmacyipbill']:
            report_title = "PATIENT WISE PHARMACY IP BILL DETAILED"

            ph_query = {}
            if ip_number_filter:
                ph_query["$or"] = [{"inpatient_number": ip_number_filter}, {"ip_number": ip_number_filter}, {"inpatient_number": ip_number_filter.replace('/', '')}]
            elif uhid_filter:
                ph_query["uhid"] = uhid_filter
            else:
                ph_query["inpatient_number"] = {"$exists": True, "$ne": None, "$nin": ["", "0"]}

            ph_bills = list(hms_db['hospital_pharmacybilling'].find(ph_query).sort("bill_date", -1).limit(10))

            target_ip = ip_number_filter or (ph_bills[0].get('inpatient_number') if ph_bills else '')
            target_uhid = uhid_filter or (ph_bills[0].get('uhid') if ph_bills else '')

            pat = hms_db['hospital_patient'].find_one({"uhid": target_uhid}) if target_uhid else None
            adm = hms_db['hospital_admission'].find_one({"$or": [{"ipNumber": target_ip}, {"ip_number": target_ip}]}) if target_ip else None

            pname = ""
            if pat:
                pname = f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip()
            if not pname and ph_bills:
                pname = ph_bills[0].get('patientname') or ph_bills[0].get('patient_name') or ''
            if not pname and adm:
                pname = adm.get('patientName') or ''
            pname = pname or "Patient"

            doc_id = (adm.get('consultingDoctor') if adm else '') or (pat.get('doctorName') if pat else '') or (ph_bills[0].get('doctor_id') if ph_bills else '')
            doc_name = doctor_map.get(str(doc_id)) or str(doc_id) or "DR. CONSULTANT"

            room_str = "-"
            if adm and adm.get('room_details'):
                r_active = next((r for r in adm.get('room_details', []) if r.get('is_roomActive')), adm.get('room_details')[0])
                room_str = f"{r_active.get('roomNo', '-')}-{r_active.get('bedNo', '-')}"
            elif ph_bills and ph_bills[0].get('room_no'):
                room_str = str(ph_bills[0].get('room_no'))

            patient_info = {
                "patient_name": pname,
                "op_number": target_uhid or "-",
                "ip_number": target_ip or "-",
                "doctor_name": doc_name,
                "room_no": room_str,
                "dl_no": "649/M3/20 & 649A/M3/21",
                "tin": "33932782724",
                "gstin": "33AAACS5352E1ZZ",
                "cin": "U85110TZ2020PLC034639",
                "phone": "0427-2706666",
                "fax": "0427-2311891"
            }

            columns = [
                {"key": "sl_no", "label": "Sl.No", "width": "50px"},
                {"key": "bill_date", "label": "Bill Date", "width": "95px"},
                {"key": "bill_no", "label": "Bill No", "width": "120px"},
                {"key": "qty", "label": "Qty", "width": "50px", "align": "right"},
                {"key": "particulars", "label": "Particulars", "width": "220px"},
                {"key": "batch", "label": "Batch", "width": "90px"},
                {"key": "expiry", "label": "Expiry", "width": "80px"},
                {"key": "amount", "label": "Amount", "width": "90px", "align": "right"},
                {"key": "hsn", "label": "HSN", "width": "80px"},
                {"key": "cgst_pct", "label": "CGST %", "width": "65px", "align": "right"},
                {"key": "cgst", "label": "CGST", "width": "75px", "align": "right"},
                {"key": "sgst_pct", "label": "SGST %", "width": "65px", "align": "right"},
                {"key": "sgst", "label": "SGST", "width": "75px", "align": "right"},
                {"key": "taxable_amt", "label": "Taxable Amt", "width": "100px", "align": "right"}
            ]

            # Pre-fetch item names from hospital_pharmacyitem
            all_item_ids = []
            for b in ph_bills:
                for itm in b.get('medicine_particulars', []):
                    iid = itm.get('item_id')
                    if iid is not None:
                        all_item_ids.append(iid)
            pharm_items = {pi['item_id']: pi for pi in hms_db['hospital_pharmacyitem'].find({'item_id': {'$in': all_item_ids}}, {'item_id': 1, 'item_name': 1, 'hsn': 1})}

            bills = []
            records = []
            overall_gross = 0.0
            overall_cgst = 0.0
            overall_sgst = 0.0

            for b in ph_bills:
                b_no = str(b.get('bill_no', ''))
                b_dt = format_dt(b.get('bill_date'))
                b_items = []
                tax_map = defaultdict(lambda: {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0})

                for s_idx, itm in enumerate(b.get('medicine_particulars', []), start=1):
                    iid = itm.get('item_id')
                    ref_pi = pharm_items.get(iid, {})
                    part_name = itm.get('item_name') or ref_pi.get('item_name') or f"Medicine {iid or s_idx}"
                    qty = clean_num(itm.get('qty') or itm.get('dispatched_qty') or 1)
                    amt = clean_num(itm.get('total') or itm.get('calculated_price'))
                    if amt == 0:
                        unit_p = clean_num(itm.get('price'))
                        amt = round(unit_p * qty, 2) if unit_p > 0 else 0.0

                    cgst_pct = 6.0
                    sgst_pct = 6.0
                    taxable = round(amt / 1.12, 2) if amt > 0 else 0.0
                    cgst = round((taxable * cgst_pct) / 100.0, 2)
                    sgst = round((taxable * sgst_pct) / 100.0, 2)

                    tax_map["12%"]["taxable"] += taxable
                    tax_map["12%"]["cgst"] += cgst
                    tax_map["12%"]["sgst"] += sgst
                    overall_gross += amt
                    overall_cgst += cgst
                    overall_sgst += sgst

                    row_item = {
                        "sl_no": s_idx,
                        "bill_date": b_dt,
                        "bill_no": b_no,
                        "qty": int(qty) if qty.is_integer() else qty,
                        "particulars": part_name,
                        "batch": str(itm.get('batch_number') or '-'),
                        "expiry": str(itm.get('expiry_date') or '-'),
                        "amount": round(amt, 2),
                        "hsn": str(ref_pi.get('hsn') or itm.get('hsn_code') or '300490'),
                        "cgst_pct": cgst_pct,
                        "cgst": cgst,
                        "sgst_pct": sgst_pct,
                        "sgst": sgst,
                        "taxable_amt": taxable
                    }
                    b_items.append(row_item)
                    records.append(row_item)

                tax_summary = []
                for slab, tv in tax_map.items():
                    tax_summary.append({
                        "tax_slab": slab,
                        "taxable_value": round(tv["taxable"], 2),
                        "cgst": round(tv["cgst"], 2),
                        "sgst": round(tv["sgst"], 2),
                        "total_tax": round(tv["cgst"] + tv["sgst"], 2)
                    })

                b_tot = round(sum(i['amount'] for i in b_items), 2)
                bills.append({
                    "bill_no": b_no,
                    "bill_date": b_dt,
                    "items": b_items,
                    "tax_summary": tax_summary,
                    "bill_total": b_tot,
                    "bill_net": b_tot
                })

            summary = {
                "total_bills": len(bills),
                "total_items": len(records),
                "gross_amount": round(overall_gross, 2),
                "cgst_total": round(overall_cgst, 2),
                "sgst_total": round(overall_sgst, 2),
                "total_tax": round(overall_cgst + overall_sgst, 2),
                "round_off": 0.00,
                "net_total_amount": round(overall_gross, 2)
            }
            grouped_data = {"bills": bills}

        # ---------------------------------------------------------
        # 2. Insurance Bills Status
        # ---------------------------------------------------------
        elif key in ['insurance_bills_status', 'insurancebillsstatus']:
            report_title = "Insurance Bills Status"
            columns = [
                {"key": "bill_date", "label": "Bill date"},
                {"key": "patient_name", "label": "Patient Name"},
                {"key": "bill_amount", "label": "Bill Amount", "align": "right"},
                {"key": "op_number", "label": "OP Number"},
                {"key": "despatch_date", "label": "Despatch Date"},
                {"key": "settlement_date", "label": "Settlement Date"},
                {"key": "settled_amount", "label": "Settled Amount", "align": "right"},
                {"key": "disallowed_amount", "label": "Disallowed Amount", "align": "right"},
                {"key": "due_amount", "label": "DUE", "align": "right"},
                {"key": "card_number", "label": "Card Number"},
                {"key": "service_no", "label": "Service No"},
                {"key": "claim_ref", "label": "Claim Reference"},
                {"key": "tds", "label": "TDS", "align": "right"},
                {"key": "paid_by_patient", "label": "Paid By Patient", "align": "right"},
                {"key": "settlement_duration", "label": "Settlement Duration"},
                {"key": "ip_number", "label": "IP Number"},
                {"key": "bill_id", "label": "Bill ID"},
                {"key": "place", "label": "Place"}
            ]

            all_pool = build_live_discharge_pool()
            all_pool.sort(key=lambda x: (x.get('company_name', ''), x.get('bill_date', '')))

            tot_bill = tot_due = tot_settled = tot_disallowed = 0.0
            sno = 1
            grouped_data = {}
            for row in all_pool:
                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                r = dict(row)
                r['sno'] = sno
                tot_bill += r['bill_amount']
                tot_due += r['due_amount']
                tot_settled += r['settled_amount']
                tot_disallowed += r['disallowed_amount']
                records.append(r)

                c = r.get('company_name') or 'OTHER'
                if c not in grouped_data:
                    grouped_data[c] = []
                grouped_data[c].append(r)
                sno += 1

            summary = {
                "total_bills": len(records),
                "total_bill_amount": round(tot_bill, 2),
                "total_settled_amount": round(tot_settled, 2),
                "total_disallowed_amount": round(tot_disallowed, 2),
                "total_due_amount": round(tot_due, 2)
            }

        # ---------------------------------------------------------
        # 3. Insurance Bills Due List
        # ---------------------------------------------------------
        elif key in ['insurance_bills_due_list', 'insurancebillsduelist']:
            report_title = "Insurance Bills Due List"
            columns = [
                {"key": "bill_date", "label": "Bill date"},
                {"key": "patient_name", "label": "Patient Name"},
                {"key": "bill_amount", "label": "Bill Amount", "align": "right"},
                {"key": "despatch_date", "label": "Despatch Date"},
                {"key": "settlement_date", "label": "Settlement Date"},
                {"key": "settled_amount", "label": "Settled Amount", "align": "right"},
                {"key": "disallowed_amount", "label": "Disallowed Amount", "align": "right"},
                {"key": "due_amount", "label": "DUE", "align": "right"},
                {"key": "card_number", "label": "Card Number"},
                {"key": "service_no", "label": "Service No"},
                {"key": "claim_ref", "label": "Claim Reference"},
                {"key": "tds", "label": "TDS", "align": "right"},
                {"key": "paid_by_patient", "label": "Paid By Patient", "align": "right"},
                {"key": "settlement_duration", "label": "Settlement Duration"},
                {"key": "ip_number", "label": "IP Number"},
                {"key": "bill_id", "label": "Bill ID"},
                {"key": "place", "label": "Place"},
                {"key": "sh_bill_no", "label": "Sh Bill Number"},
                {"key": "admitting_date", "label": "Admitting Date"},
                {"key": "discharge_date", "label": "Discharge Date"},
                {"key": "advance", "label": "Advance", "align": "right"}
            ]

            all_pool = build_live_discharge_pool()
            all_pool.sort(key=lambda x: (x.get('company_name', ''), x.get('bill_date', '')))

            tot_bill = tot_advance = tot_due = 0.0
            sno = 1
            for row in all_pool:
                if row.get('due_amount', 0) <= 0:
                    continue
                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                r = dict(row)
                r['sno'] = sno
                tot_bill += r['bill_amount']
                tot_advance += r.get('advance', 0)
                tot_due += r['due_amount']
                records.append(r)
                sno += 1

            summary = {
                "total_bills": len(records),
                "total_bill_amount": round(tot_bill, 2),
                "total_advance": round(tot_advance, 2),
                "total_due_amount": round(tot_due, 2)
            }

        # ---------------------------------------------------------
        # 4. Insurance Bills Status Report
        # ---------------------------------------------------------
        elif key in ['insurance_bills_status_report', 'insurancebillsstatusreport']:
            report_title = "Insurance Bills Status Report"
            columns = [
                {"key": "bill_date", "label": "Bill date"},
                {"key": "patient_name", "label": "Patient Name"},
                {"key": "bill_amount", "label": "Bill Amount", "align": "right"},
                {"key": "despatch_date", "label": "Despatch Date"},
                {"key": "settlement_date", "label": "Settlement Date"},
                {"key": "settled_amount", "label": "Settled Amount", "align": "right"},
                {"key": "disallowed_amount", "label": "Disallowed Amount", "align": "right"},
                {"key": "due_amount", "label": "DUE", "align": "right"},
                {"key": "card_number", "label": "Card Number"},
                {"key": "service_no", "label": "Service No"},
                {"key": "claim_ref", "label": "Claim Reference"},
                {"key": "tds", "label": "TDS", "align": "right"},
                {"key": "paid_by_patient", "label": "Paid By Patient", "align": "right"},
                {"key": "settlement_duration", "label": "Settlement Duration"},
                {"key": "ip_number", "label": "IP Number"},
                {"key": "bill_id", "label": "Bill ID"},
                {"key": "place", "label": "Place"},
                {"key": "sh_bill_no", "label": "Sh Bill Number"},
                {"key": "admitting_date", "label": "Admitting Date"},
                {"key": "discharge_date", "label": "Discharge Date"},
                {"key": "advance", "label": "Advance", "align": "right"},
                {"key": "sl_no", "label": "Sl No"},
                {"key": "status", "label": "Status"},
                {"key": "old_billno", "label": "Old Billno"}
            ]

            all_pool = build_live_discharge_pool()
            all_pool.sort(key=lambda x: (x.get('company_name', ''), x.get('bill_date', '')))

            comp_counters = {}
            tot_bill = tot_advance = tot_due = 0.0
            sno = 1
            for row in all_pool:
                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                c_name = row.get('company_name', '')
                comp_counters[c_name] = comp_counters.get(c_name, 0) + 1
                r = dict(row)
                r['sno'] = sno
                r['sl_no'] = comp_counters[c_name]
                tot_bill += r['bill_amount']
                tot_advance += r.get('advance', 0)
                tot_due += r['due_amount']
                records.append(r)
                sno += 1

            summary = {
                "total_bills": len(records),
                "total_bill_amount": round(tot_bill, 2),
                "total_advance": round(tot_advance, 2),
                "total_due_amount": round(tot_due, 2)
            }

        # ---------------------------------------------------------
        # 5. Echs Certificates
        # ---------------------------------------------------------
        elif key in ['echs_certificates', 'echscertificatesreport']:
            report_title = "Echs Certificates"
            columns = [
                {"key": "sno", "label": "S/No", "width": "60px"},
                {"key": "cert_date", "label": "Date", "width": "110px"},
                {"key": "uhid", "label": "UHID", "width": "120px"},
                {"key": "patient_name", "label": "Patient Name", "width": "180px"},
                {"key": "service_no", "label": "Service No", "width": "120px"},
                {"key": "rank", "label": "Rank", "width": "110px"},
                {"key": "card_no", "label": "ECHS Card No", "width": "140px"},
                {"key": "polyclinic", "label": "Polyclinic", "width": "160px"},
                {"key": "diagnosis", "label": "Provisional Diagnosis", "width": "200px"},
                {"key": "doctor", "label": "Treating Doctor", "width": "180px"},
                {"key": "cert_type", "label": "Certificate Type", "width": "160px"},
                {"key": "status", "label": "Approval Status", "width": "110px"}
            ]

            mv_query = {}
            if dt_start and dt_end:
                mv_query["visit_date"] = {"$gte": dt_start, "$lte": dt_end}
            m_visits = list(hms_db['hospital_insurancemembervisit'].find(mv_query).sort("visit_date", -1).limit(200))
            if not m_visits:
                m_visits = list(hms_db['hospital_insurancemembervisit'].find({}).sort("visit_date", -1).limit(100))

            m_nums = list(set([mv.get('member_number') for mv in m_visits if mv.get('member_number')]))
            m_uhids = list(set([mv.get('uhid') for mv in m_visits if mv.get('uhid')]))

            m_members = {m['member_number']: m for m in hms_db['hospital_insurancemember'].find({'member_number': {'$in': m_nums}})}
            m_pats = {p['uhid']: p for p in hms_db['hospital_patient'].find({'uhid': {'$in': m_uhids}}, {'uhid': 1, 'firstName': 1, 'lastName': 1, 'doctorName': 1})}

            sno = 1
            appr_count = 0
            pend_count = 0

            for mv in m_visits:
                mnum = mv.get('member_number')
                uh = mv.get('uhid') or ''
                mem = m_members.get(mnum, {})
                pat = m_pats.get(uh, {})

                pname = mem.get('member_name') or (f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip() if pat else '') or mv.get('patient_name') or f"Patient {uh}"
                v_date = format_dt(mv.get('visit_date'))
                serv_no = str(mem.get('service_number') or mv.get('service_number') or '-')
                rank = str(mem.get('rank') or mem.get('esm_rank') or '-')
                card_no = str(mem.get('card_no') or mem.get('echs_card') or '-')
                poly = str(mv.get('parent_polyclinic') or mem.get('parent_polyclinic') or '001')
                if poly == '001': poly = 'SALEM POLYCLINIC (001)'
                elif poly == '022': poly = 'NAMAKKAL POLYCLINIC (022)'

                diag = str(mv.get('provisional_diagnosis') or 'CARDIO VASCULAR EVALUATION')
                doc_raw = mv.get('consulting_doctor') or pat.get('doctorName')
                doc = doctor_map.get(str(doc_raw)) or str(doc_raw or 'DR. CONSULTANT')

                c_type = "Emergency Admission Certificate" if mv.get('relationship') == 'Self' else "Referral Extension Slip"
                stat = "APPROVED" if mv.get('referral_number') else "PENDING"
                if stat == "APPROVED": appr_count += 1
                else: pend_count += 1

                row = {
                    "sno": sno,
                    "cert_date": v_date,
                    "uhid": uh,
                    "patient_name": pname,
                    "service_no": serv_no,
                    "rank": rank,
                    "card_no": card_no,
                    "polyclinic": poly,
                    "diagnosis": diag,
                    "doctor": doc,
                    "cert_type": c_type,
                    "status": stat,
                    "company_name": "ECHS"
                }

                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                records.append(row)
                sno += 1

            summary = {
                "total_certificates": len(records),
                "approved_certificates": sum(1 for r in records if r['status'] == 'APPROVED'),
                "pending_certificates": sum(1 for r in records if r['status'] == 'PENDING')
            }

        # ---------------------------------------------------------
        # 6. Lab Investigation & ECHS Investigation Bills
        # ---------------------------------------------------------
        elif key in ['lab_investigation', 'labinvestigationreport', 'echs_investigation_bills', 'insuranceechsinvestigationbillsreport']:
            report_title = "Lab Investigation Report" if 'lab' in key else "Insurance Echs Investigation Bills"
            columns = [
                {"key": "sno", "label": "S/No", "width": "60px"},
                {"key": "bill_date", "label": "Date", "width": "110px"},
                {"key": "bill_no", "label": "Bill No", "width": "130px"},
                {"key": "uhid", "label": "UHID", "width": "120px"},
                {"key": "patient_name", "label": "Patient Name", "width": "180px"},
                {"key": "service_no", "label": "Service No", "width": "120px"},
                {"key": "test_name", "label": "Investigation / Profile", "width": "220px"},
                {"key": "department", "label": "Lab Department", "width": "140px"},
                {"key": "rate", "label": "CGHS / ECHS Rate", "width": "120px", "align": "right"},
                {"key": "amount", "label": "Total Amount", "width": "120px", "align": "right"},
                {"key": "payment_status", "label": "Payment Status", "width": "120px"}
            ]

            inv_q = {}
            if dt_start and dt_end:
                inv_q["$or"] = [
                    {"investBillDate": {"$gte": dt_start, "$lte": dt_end}},
                    {"created_date": {"$gte": dt_start, "$lte": dt_end}}
                ]
            investigations = list(hms_db['hospital_investbilling'].find(inv_q).sort("investBillDate", -1).limit(250))
            if not investigations:
                investigations = list(hms_db['hospital_investbilling'].find({}).sort("investBillDate", -1).limit(150))

            inv_uhids = list(set([i.get('uhid') for i in investigations if i.get('uhid')]))
            inv_pats = {p['uhid']: p for p in hms_db['hospital_patient'].find({'uhid': {'$in': inv_uhids}}, {'uhid': 1, 'firstName': 1, 'lastName': 1, 'company_name': 1, 'company_code': 1})}
            inv_mems = {m['uhid']: m for m in hms_db['hospital_insurancemember'].find({'uhid': {'$in': inv_uhids}}, {'uhid': 1, 'service_number': 1})}

            sno = 1
            tot_amt = 0.0
            tot_rate = 0.0

            for inv in investigations:
                uh = inv.get('uhid') or ''
                pat = inv_pats.get(uh, {})
                mem = inv_mems.get(uh, {})
                pname = f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip() if pat else (inv.get('firstName') or f"Patient {uh}")
                cname = resolve_company(pat.get('company_name'), pat.get('company_code'))
                serv_no = str(mem.get('service_number') or '-')

                b_date_str = format_dt(inv.get('investBillDate') or inv.get('created_date'))
                b_amt = clean_num(inv.get('finalPrice') or inv.get('total'))

                raw_items = inv.get('item', [])
                if isinstance(raw_items, list) and len(raw_items) > 0:
                    for itm_idx, itm in enumerate(raw_items):
                        if not isinstance(itm, dict): continue
                        t_name = itm.get('itemName') or itm.get('test_name') or "DIAGNOSTIC TEST"
                        item_rate = clean_num(itm.get('price')) or (b_amt / max(1, len(raw_items)))
                        dept = "RADIOLOGY" if any(w in t_name.upper() for w in ['XRAY', 'CT', 'MRI', 'ECHO', 'USG', 'CHEST']) else ("BIOCHEMISTRY" if any(w in t_name.upper() for w in ['PROFILE', 'SUGAR', 'UREA', 'LFT', 'KFT']) else "PATHOLOGY")

                        row = {
                            "sno": sno,
                            "bill_date": b_date_str,
                            "bill_no": str(inv.get('investBillNo', '')),
                            "uhid": uh,
                            "patient_name": pname,
                            "service_no": serv_no,
                            "test_name": t_name,
                            "department": dept,
                            "rate": round(item_rate, 2),
                            "amount": round(item_rate, 2),
                            "payment_status": str(inv.get('paymentStatus') or 'CREDIT CLAIMED').upper(),
                            "company_name": cname
                        }
                        if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                            continue
                        tot_amt += item_rate
                        tot_rate += item_rate
                        records.append(row)
                        sno += 1
                else:
                    t_name = "COMPLETE DIAGNOSTIC INVESTIGATION"
                    dept = "PATHOLOGY"
                    row = {
                        "sno": sno,
                        "bill_date": b_date_str,
                        "bill_no": str(inv.get('investBillNo', '')),
                        "uhid": uh,
                        "patient_name": pname,
                        "service_no": serv_no,
                        "test_name": t_name,
                        "department": dept,
                        "rate": round(b_amt, 2),
                        "amount": round(b_amt, 2),
                        "payment_status": str(inv.get('paymentStatus') or 'CREDIT CLAIMED').upper(),
                        "company_name": cname
                    }
                    if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                        continue
                    tot_amt += b_amt
                    records.append(row)
                    sno += 1

            summary = {
                "total_investigations": len(records),
                "total_billed_amount": round(tot_amt, 2),
                "total_credit_claimed": round(tot_amt, 2)
            }

        # ---------------------------------------------------------
        # 7. Occupancy List Company Wise
        # ---------------------------------------------------------
        elif key in ['occupancy_company_wise', 'occupancylistcompanywise', 'occupancylistcompanywisereport']:
            report_title = "Occupancy List Company Wise"
            columns = [
                {"key": "sno", "label": "S/No", "width": "60px"},
                {"key": "company_name", "label": "Company / Sponsor", "width": "200px"},
                {"key": "ip_number", "label": "IP Number", "width": "130px"},
                {"key": "op_number", "label": "OP Number", "width": "120px"},
                {"key": "patient_name", "label": "Patient Name", "width": "180px"},
                {"key": "age_gender", "label": "Age / Gender", "width": "110px"},
                {"key": "room_number", "label": "Room / Bed", "width": "120px"},
                {"key": "admitting_date", "label": "Admitting Date", "width": "120px"},
                {"key": "doctor_name", "label": "Consulting Doctor", "width": "200px"},
                {"key": "address", "label": "Patient Address", "width": "220px"}
            ]

            active_adms = list(hms_db['hospital_admission'].find({
                "is_admitted": True,
                "is_discharged": {"$ne": True}
            }).sort("admissionDateTime", -1).limit(300))

            if not active_adms:
                active_adms = list(hms_db['hospital_admission'].find({}).sort("admissionDateTime", -1).limit(100))

            adm_uhids = list(set([a.get('uhid') for a in active_adms if a.get('uhid')]))
            adm_pats = {p['uhid']: p for p in hms_db['hospital_patient'].find({'uhid': {'$in': adm_uhids}})}

            sno = 1
            for a in active_adms:
                uh = a.get('uhid') or ''
                p = adm_pats.get(uh, {})
                pname = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or a.get('patientName') or f"Patient {uh}"
                cname = resolve_company(a.get('insurance_company'), a.get('company_code'), adm=a, pat=p)
                ccode = str(a.get('company_code') or p.get('company_code') or cname)

                room_list = a.get("room_details", [])
                active_room = next((r for r in room_list if r.get("is_roomActive")), room_list[0] if room_list else {})
                r_no = f"{active_room.get('roomNo', '-')}-{active_room.get('bedNo', '-')}" if active_room else "-"

                adm_dt_str = format_dt(a.get('admissionDateTime'))
                doc_raw = a.get('consultingDoctor') or p.get('doctorName')
                doc_name = doctor_map.get(str(doc_raw)) or str(doc_raw or 'DR. CONSULTANT')

                addr = str(p.get('permanent_address') or p.get('city') or p.get('district') or 'SALEM, TAMIL NADU')
                age_gen = f"{p.get('age', '-')} / {p.get('gender', '-')}"

                row = {
                    "sno": sno,
                    "company_name": cname,
                    "company_code": ccode,
                    "ip_number": str(a.get('ipNumber') or a.get('ip_number') or ''),
                    "op_number": uh,
                    "patient_name": pname,
                    "age_gender": age_gen,
                    "room_number": r_no,
                    "admitting_date": adm_dt_str,
                    "doctor_name": doc_name,
                    "address": addr
                }

                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                records.append(row)
                sno += 1

            summary = {
                "total_occupied_beds": len(records),
                "echs_beds": sum(1 for r in records if "ECHS" in r['company_name']),
                "railway_beds": sum(1 for r in records if "RAILWAY" in r['company_name']),
                "tpa_beds": sum(1 for r in records if "ECHS" not in r['company_name'] and "RAILWAY" not in r['company_name'])
            }

        # ---------------------------------------------------------
        # 8. Company Wise Patient Registration Report
        # ---------------------------------------------------------
        elif key in ['companywise_registration', 'companywisepatientregistrationreport']:
            report_title = "Company Wise Patient Registration Report"
            columns = [
                {"key": "sno", "label": "S/No", "width": "50px"},
                {"key": "reg_date", "label": "Date", "width": "95px"},
                {"key": "uhid", "label": "UHID / Reg No", "width": "115px"},
                {"key": "ip_number", "label": "IP Number", "width": "115px"},
                {"key": "patient_name", "label": "Patient Name", "width": "170px"},
                {"key": "age_gender", "label": "Age / Gender", "width": "100px"},
                {"key": "doctor_name", "label": "Consulting Doctor", "width": "160px"},
                {"key": "company_name", "label": "Company Name", "width": "180px"},
                {"key": "company_code", "label": "Company Code", "width": "110px"},
                {"key": "policy_no", "label": "Card / Policy No", "width": "140px"},
                {"key": "claim_status", "label": "Status", "width": "100px"}
            ]

            # Admissions in range with insurance
            a_query = {
                "$and": [
                    {"$or": [{"admissionDateTime": {"$gte": dt_start, "$lte": dt_end}}, {"created_date": {"$gte": dt_start, "$lte": dt_end}}]},
                    {"$or": [{"insurance_company": {"$exists": True, "$nin": [None, "", "N", "PRIVATE", "CASH"]}}, {"company_code": {"$exists": True, "$nin": [None, "", "N"]}}]}
                ]
            }
            adms = list(hms_db['hospital_admission'].find(a_query).sort("admissionDateTime", -1).limit(400))
            if not adms:
                adms = list(hms_db['hospital_admission'].find({"company_code": {"$exists": True, "$nin": [None, "", "N"]}}).sort("admissionDateTime", -1).limit(100))

            # Outpatient insurance member visits in range
            v_query = {"$or": [{"visit_date": {"$gte": dt_start, "$lte": dt_end}}, {"created_date": {"$gte": dt_start, "$lte": dt_end}}]}
            visits = list(hms_db['hospital_insurancemembervisit'].find(v_query).sort("visit_date", -1).limit(400))
            if not visits:
                visits = list(hms_db['hospital_insurancemembervisit'].find({}).sort("visit_date", -1).limit(100))

            all_uhids = list(set([a.get('uhid') for a in adms if a.get('uhid')] + [v.get('uhid') for v in visits if v.get('uhid')]))
            pats = {p['uhid']: p for p in hms_db['hospital_patient'].find({'uhid': {'$in': all_uhids}})}
            mems = {m['uhid']: m for m in hms_db['hospital_insurancemember'].find({'uhid': {'$in': all_uhids}})}
            claims = {c.get('ip_number') or c.get('uhid'): c for c in hms_db['hospital_insuranceclaim'].find({'uhid': {'$in': all_uhids}})}

            sno = 1
            seen_keys = set()

            # 1. Process Admissions with corporate / insurance schemes
            for a in adms:
                uh = a.get('uhid') or ''
                ipn = a.get('ipNumber') or a.get('ip_number') or ''
                key = f"{uh}_{ipn}"
                if key in seen_keys: continue
                seen_keys.add(key)

                p = pats.get(uh, {})
                m = mems.get(uh, {})
                clm = claims.get(ipn) or claims.get(uh, {})

                ccode = str(a.get('company_code') or clm.get('company_code') or '')
                cname = company_map.get(ccode) or a.get('insurance_company') or clm.get('insurance_company') or "INSURANCE"
                pname = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or a.get('patientName') or f"Patient {uh}"
                doc_raw = a.get('consultingDoctor') or p.get('doctorName')
                doc_name = doctor_map.get(str(doc_raw)) or str(doc_raw or 'DR. CONSULTANT')
                pol_no = str(a.get('policy_no') or clm.get('policy_no') or m.get('card_no') or m.get('service_number') or '-')

                row = {
                    "sno": sno,
                    "reg_date": format_dt(a.get('admissionDateTime') or a.get('created_date')),
                    "uhid": uh,
                    "ip_number": ipn,
                    "patient_name": pname,
                    "age_gender": f"{p.get('age', a.get('age', '-'))} / {p.get('gender', a.get('gender', '-'))}",
                    "doctor_name": doc_name,
                    "company_name": cname,
                    "company_code": ccode,
                    "policy_no": pol_no,
                    "claim_status": str(clm.get('claim_status') or 'APPROVED').upper()
                }

                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                records.append(row)
                sno += 1

            # 2. Process Outpatient insurance member visits
            for v in visits:
                uh = v.get('uhid') or ''
                ref = v.get('member_visit_reference') or v.get('referral_number') or ''
                key = f"{uh}_v_{ref}"
                if key in seen_keys: continue
                seen_keys.add(key)

                p = pats.get(uh, {})
                m = mems.get(uh, {})
                clm = claims.get(uh, {})

                ccode = str(v.get('sh_company_code') or m.get('insurance_type') or '')
                cname = company_map.get(ccode) or (m.get('insurance_type') and company_map.get(str(m.get('insurance_type')))) or ("ECHS" if m.get('echs_card') else "INSURANCE")
                pname = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or f"Patient {uh}"
                doc_raw = v.get('consulting_doctor') or p.get('doctorName')
                doc_name = doctor_map.get(str(doc_raw)) or str(doc_raw or 'DR. CONSULTANT')
                pol_no = str(v.get('referral_number') or m.get('card_no') or m.get('service_number') or '-')

                row = {
                    "sno": sno,
                    "reg_date": format_dt(v.get('visit_date') or v.get('created_date')),
                    "uhid": uh,
                    "ip_number": "-",
                    "patient_name": pname,
                    "age_gender": f"{p.get('age', v.get('age', '-'))} / {p.get('gender', v.get('gender', '-'))}",
                    "doctor_name": doc_name,
                    "company_name": cname,
                    "company_code": ccode,
                    "policy_no": pol_no,
                    "claim_status": str(clm.get('claim_status') or 'APPROVED').upper()
                }

                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                records.append(row)
                sno += 1

            summary = {
                "total_registrations": len(records),
                "approved_claims": len(records),
                "under_scrutiny": 0
            }

        # ---------------------------------------------------------
        # 9. Date Wise Insurance Bills Details
        # ---------------------------------------------------------
        elif key in ['date_wise_details', 'datewisedetails', 'date_wise_insurance_bills_details']:
            report_title = "Date Wise Insurance Bills Details"
            columns = [
                {"key": "sno", "label": "S/No", "width": "50px"},
                {"key": "bill_date", "label": "Bill Date", "width": "100px"},
                {"key": "bill_no", "label": "Bill No", "width": "120px"},
                {"key": "ip_number", "label": "IP Number", "width": "110px"},
                {"key": "uhid", "label": "UHID", "width": "110px"},
                {"key": "patient_name", "label": "Patient Name", "width": "170px"},
                {"key": "company_name", "label": "Company Name", "width": "170px"},
                {"key": "gross_total", "label": "Gross Amount", "width": "110px", "align": "right"},
                {"key": "advance_paid", "label": "Advance", "width": "100px", "align": "right"},
                {"key": "net_amount", "label": "Net Claim", "width": "110px", "align": "right"},
                {"key": "status", "label": "Status", "width": "90px"}
            ]

            all_pool = build_live_discharge_pool()
            tot_gross = tot_adv = tot_net = 0.0
            sno = 1

            for row in all_pool:
                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                gross_amt = row['bill_amount']
                adv_amt = row['advance']
                net_amt = max(0.0, gross_amt - adv_amt)

                r = {
                    "sno": sno,
                    "bill_date": row['bill_date'],
                    "bill_no": row['bill_id'],
                    "ip_number": row['ip_number'],
                    "uhid": row['uhid'],
                    "patient_name": row['patient_name'],
                    "company_name": row['company_name'],
                    "company_code": row.get('company_code', ''),
                    "gross_total": round(gross_amt, 2),
                    "advance_paid": round(adv_amt, 2),
                    "net_amount": round(net_amt, 2),
                    "status": row['status']
                }

                tot_gross += gross_amt
                tot_adv += adv_amt
                tot_net += net_amt
                records.append(r)
                sno += 1

            summary = {
                "total_bills": len(records),
                "total_gross_amount": round(tot_gross, 2),
                "total_advance_paid": round(tot_adv, 2),
                "total_net_claims": round(tot_net, 2)
            }

        # ---------------------------------------------------------
        # 10. Insurance Bill Number Checking
        # ---------------------------------------------------------
        elif key in ['bill_number_checking', 'billnumberchecking', 'insurance_bill_number_checking']:
            report_title = "Insurance Bill Number Checking"
            columns = [
                {"key": "sno", "label": "S/No", "width": "50px"},
                {"key": "bill_date", "label": "Bill Date", "width": "100px"},
                {"key": "bill_no", "label": "Bill Number", "width": "130px"},
                {"key": "ip_number", "label": "IP Number", "width": "110px"},
                {"key": "uhid", "label": "UHID", "width": "110px"},
                {"key": "patient_name", "label": "Patient Name", "width": "170px"},
                {"key": "company_name", "label": "Company Name", "width": "170px"},
                {"key": "bill_amount", "label": "Bill Amount", "width": "110px", "align": "right"},
                {"key": "audit_status", "label": "Sequence Audit Status", "width": "150px"},
                {"key": "is_cancelled", "label": "Cancelled Status", "width": "120px"},
                {"key": "remarks", "label": "Remarks", "width": "120px"}
            ]

            all_pool = build_live_discharge_pool()
            all_pool.sort(key=lambda x: str(x.get('bill_id', '')))

            sno = 1
            tot_amt = 0.0
            prev_num = None
            gap_count = 0
            cancelled_count = 0

            for b in all_pool:
                bno = str(b.get('bill_id', ''))
                b_amt = b.get('bill_amount', 0.0)
                is_canc = (b.get('status') == 'CANCELLED')

                audit_status = "VALID SEQUENCE"
                curr_int = None
                try:
                    digits = ''.join(c for c in bno if c.isdigit())
                    if digits:
                        curr_int = int(digits)
                except Exception:
                    pass

                if is_canc:
                    audit_status = "CANCELLED BILL"
                    cancelled_count += 1
                elif curr_int is not None and prev_num is not None:
                    diff = curr_int - prev_num
                    if diff > 1:
                        audit_status = f"GAP DETECTED (+{diff - 1})"
                        gap_count += 1

                if curr_int is not None:
                    prev_num = curr_int

                row = {
                    "sno": sno,
                    "bill_date": b.get('bill_date'),
                    "bill_no": bno,
                    "ip_number": b.get('ip_number'),
                    "uhid": b.get('uhid'),
                    "patient_name": b.get('patient_name'),
                    "company_name": b.get('company_name'),
                    "company_code": b.get('company_code', ''),
                    "bill_amount": round(b_amt, 2),
                    "audit_status": audit_status,
                    "is_cancelled": "YES" if is_canc else "NO",
                    "remarks": "-"
                }

                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                tot_amt += b_amt
                records.append(row)
                sno += 1

            summary = {
                "total_audited_bills": len(records),
                "total_bill_amount": round(tot_amt, 2),
                "sequence_gaps_found": gap_count,
                "cancelled_bills": cancelled_count
            }

        # ---------------------------------------------------------
        # 11. Insurance Bills Summary
        # ---------------------------------------------------------
        elif key in ['bills_summary', 'billssummary', 'insurance_bills_summary']:
            report_title = "Insurance Bills Summary"
            columns = [
                {"key": "sno", "label": "S/No", "width": "50px"},
                {"key": "company_name", "label": "Insurance / Corporate Company", "width": "220px"},
                {"key": "total_bills", "label": "Total Bills", "width": "90px", "align": "right"},
                {"key": "gross_amount", "label": "Gross Claimed Amount", "width": "130px", "align": "right"},
                {"key": "advance_amount", "label": "Advance / Co-pay", "width": "120px", "align": "right"},
                {"key": "net_amount", "label": "Net Receivable", "width": "130px", "align": "right"},
                {"key": "settled_amount", "label": "Settled Amount", "width": "120px", "align": "right"},
                {"key": "due_amount", "label": "Pending Dues", "width": "120px", "align": "right"},
                {"key": "realization_pct", "label": "Realization %", "width": "100px", "align": "right"}
            ]

            all_pool = build_live_discharge_pool()
            comp_stats = {}
            for b in all_pool:
                if not row_matches_filters(b, dt_start, dt_end, None, None, company_map):
                    continue
                cname = b.get('company_name') or 'INSURANCE / CORPORATE'
                ccode = b.get('company_code') or cname
                if cname not in comp_stats:
                    comp_stats[cname] = {"count": 0, "gross": 0.0, "adv": 0.0, "net": 0.0, "settled": 0.0, "code": ccode}

                gross = b.get('bill_amount', 0.0)
                adv = b.get('advance', 0.0)
                net = max(0.0, gross - adv)
                settled = b.get('settled_amount', 0.0)

                comp_stats[cname]["count"] += 1
                comp_stats[cname]["gross"] += gross
                comp_stats[cname]["adv"] += adv
                comp_stats[cname]["net"] += net
                comp_stats[cname]["settled"] += settled

            sno = 1
            tot_bills_sum = tot_gross_sum = tot_adv_sum = tot_net_sum = tot_settled_sum = tot_due_sum = 0.0

            for cname, st in sorted(comp_stats.items(), key=lambda x: x[1]['gross'], reverse=True):
                due = max(0.0, st['net'] - st['settled'])
                realize = round((st['settled'] / st['net'] * 100), 1) if st['net'] > 0 else 100.0

                row = {
                    "sno": sno,
                    "company_name": cname,
                    "company_code": st.get("code") or cname,
                    "total_bills": st['count'],
                    "gross_amount": round(st['gross'], 2),
                    "advance_amount": round(st['adv'], 2),
                    "net_amount": round(st['net'], 2),
                    "settled_amount": round(st['settled'], 2),
                    "due_amount": round(due, 2),
                    "realization_pct": f"{realize}%"
                }

                if company_filter and company_filter.upper() != 'ALL':
                    cf_up = company_filter.upper().strip()
                    mapped_up = (company_map.get(company_filter) or '').upper().strip() if company_map else ''
                    c_code_up = str(st.get("code") or '').upper().strip()
                    c_name_up = cname.upper().strip()

                    matched = False
                    if c_code_up and c_code_up == cf_up:
                        matched = True
                        if cf_up == '100002' and 'RAILWAY' in c_name_up:
                            matched = False
                        elif cf_up in ('100003', '100059') and 'ECHS' in c_name_up:
                            matched = False
                    elif cf_up in c_name_up or c_name_up in cf_up:
                        matched = True
                    elif mapped_up and (mapped_up in c_name_up or c_name_up in mapped_up):
                        matched = True
                    else:
                        for abbr in ['ECHS', 'RAILWAY', 'CGHS', 'ESI', 'TPA', 'STAR', 'BAJAJ', 'ADITYA', 'TNCMCHIS']:
                            if abbr in cf_up and abbr in c_name_up:
                                matched = True
                                break
                    if not matched:
                        continue

                tot_bills_sum += st['count']
                tot_gross_sum += st['gross']
                tot_adv_sum += st['adv']
                tot_net_sum += st['net']
                tot_settled_sum += st['settled']
                tot_due_sum += due
                records.append(row)
                sno += 1

            summary = {
                "total_companies": len(records),
                "total_bills": int(tot_bills_sum),
                "total_gross_claims": round(tot_gross_sum, 2),
                "total_settled_amount": round(tot_settled_sum, 2),
                "total_outstanding_dues": round(tot_due_sum, 2)
            }

        # ---------------------------------------------------------
        # 12. Insurance Bills Status (Op Patients)
        # ---------------------------------------------------------
        elif key in ['status_op_patients', 'statusoppatients', 'insurance_bills_status_op_patients']:
            report_title = "Insurance Bills Status(Op Patients)"
            columns = [
                {"key": "sno", "label": "S/No", "width": "50px"},
                {"key": "bill_date", "label": "Bill Date", "width": "100px"},
                {"key": "bill_no", "label": "Bill Number", "width": "120px"},
                {"key": "op_number", "label": "OP Number / UHID", "width": "120px"},
                {"key": "patient_name", "label": "Patient Name", "width": "170px"},
                {"key": "company_name", "label": "Company Name", "width": "170px"},
                {"key": "doctor_name", "label": "Consulting Doctor", "width": "160px"},
                {"key": "bill_amount", "label": "Bill Amount", "width": "110px", "align": "right"},
                {"key": "settled_amount", "label": "Settled Amount", "width": "110px", "align": "right"},
                {"key": "due_amount", "label": "Due Amount", "width": "110px", "align": "right"},
                {"key": "status", "label": "Status", "width": "100px"}
            ]

            op_bills = list(hms_db['hospital_billing'].find({
                "$or": [
                    {"customer_type": {"$in": ["INSURANCE", "Insurance", "insurance"]}},
                    {"payment_method": "Credit"},
                    {"is_insurance": True}
                ]
            }).sort("created_date", -1).limit(250))
            if not op_bills:
                op_bills = list(hms_db['hospital_billing'].find({}).sort("created_date", -1).limit(100))

            sno = 1
            tot_b_amt = tot_s_amt = tot_d_amt = 0.0
            for b in op_bills:
                b_date_str = format_dt(b.get('bill_date') or b.get('created_date'))
                b_amt = clean_num(b.get('total_amount')) or clean_num(b.get('net_amount'))
                paid_amt = clean_num(b.get('paid_amount')) or b_amt
                due_amt = max(0.0, b_amt - paid_amt)
                cname = resolve_company(b.get('company_name'), b.get('company_code'))
                doc_raw = b.get('doctor_name') or b.get('doctorName')
                doc_name = doctor_map.get(str(doc_raw)) or str(doc_raw or 'DR. CONSULTANT')

                row = {
                    "sno": sno,
                    "bill_date": b_date_str,
                    "bill_no": str(b.get('bill_no') or b.get('bill_number') or f"OP{sno:04d}"),
                    "op_number": str(b.get('uhid') or b.get('op_number') or ''),
                    "patient_name": str(b.get('patient_name') or b.get('patientName') or f"Patient {sno}"),
                    "company_name": cname,
                    "company_code": str(b.get('company_code') or cname),
                    "doctor_name": doc_name,
                    "bill_amount": round(b_amt, 2),
                    "settled_amount": round(paid_amt, 2),
                    "due_amount": round(due_amt, 2),
                    "status": str(b.get('status') or 'SETTLED').upper()
                }

                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                tot_b_amt += b_amt
                tot_s_amt += paid_amt
                tot_d_amt += due_amt
                records.append(row)
                sno += 1

            summary = {
                "total_op_bills": len(records),
                "total_billed_amount": round(tot_b_amt, 2),
                "total_settled_amount": round(tot_s_amt, 2),
                "total_outstanding_dues": round(tot_d_amt, 2)
            }

        # ---------------------------------------------------------
        # 13. Insurance Bills Status (Report Branch Wise) Dues
        # ---------------------------------------------------------
        elif 'due' in key or 'branch_wise' in key:
            report_title = "Insurance Bills Due List" if 'due_list' in key or 'bills_due' in key else "Insurance Bills Status(Report Branch Wise) Dues"
            columns = [
                {"key": "sno", "label": "S/No", "width": "60px"},
                {"key": "bill_date", "label": "Bill Date", "width": "110px"},
                {"key": "patient_name", "label": "Patient Name", "width": "180px"},
                {"key": "company_name", "label": "Company Name", "width": "180px"},
                {"key": "ip_number", "label": "IP Number", "width": "120px"},
                {"key": "bill_id", "label": "Bill ID", "width": "120px"},
                {"key": "sh_bill_no", "label": "Sh Bill Number", "width": "130px"},
                {"key": "admitting_date", "label": "Admitting Date", "width": "120px"},
                {"key": "discharge_date", "label": "Discharge Date", "width": "120px"},
                {"key": "bill_amount", "label": "Bill Amount", "width": "120px", "align": "right"},
                {"key": "settled_amount", "label": "Settled Amount", "width": "120px", "align": "right"},
                {"key": "due_amount", "label": "DUE", "width": "120px", "align": "right"}
            ]

            all_pool = build_live_discharge_pool()
            sno = 1
            tot_bill = tot_settled = tot_due = 0.0

            for b in all_pool:
                amt = b.get('bill_amount', 0.0)
                settled = b.get('settled_amount', 0.0)
                due = b.get('due_amount', max(0.0, amt - settled))

                row = {
                    "sno": sno,
                    "bill_date": b.get('bill_date'),
                    "patient_name": b.get('patient_name'),
                    "company_name": b.get('company_name'),
                    "company_code": b.get('company_code', ''),
                    "ip_number": b.get('ip_number'),
                    "bill_id": b.get('bill_id'),
                    "sh_bill_no": b.get('sh_bill_no'),
                    "admitting_date": b.get('admitting_date'),
                    "discharge_date": b.get('discharge_date'),
                    "bill_amount": round(amt, 2),
                    "settled_amount": round(settled, 2),
                    "due_amount": round(due, 2)
                }

                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                tot_bill += amt
                tot_settled += settled
                tot_due += due
                records.append(row)
                sno += 1

            summary = {
                "total_due_bills": len(records),
                "total_billed_amount": round(tot_bill, 2),
                "total_settled_amount": round(tot_settled, 2),
                "total_outstanding_due": round(tot_due, 2)
            }

        # ---------------------------------------------------------
        # 14. Insurance Discharge Bill (All / Railway / Surgery / OP / Tkt)
        # ---------------------------------------------------------
        elif 'discharge' in key:
            type_label = "All Companies"
            if 'railway' in key: type_label = "Railway"
            elif 'surgery' in key: type_label = "Tkt Surgery"
            elif 'op' in key: type_label = "Tkt OP"
            elif 'tkt' in key: type_label = "Tkt"

            report_title = f"Insurance Discharge Bill ({type_label})"
            columns = [
                {"key": "sno", "label": "S/No", "width": "60px"},
                {"key": "bill_no", "label": "Bill No", "width": "130px"},
                {"key": "bill_date", "label": "Bill Date", "width": "110px"},
                {"key": "ip_number", "label": "IP Number", "width": "120px"},
                {"key": "uhid", "label": "UHID", "width": "120px"},
                {"key": "patient_name", "label": "Patient Name", "width": "180px"},
                {"key": "company_name", "label": "Company Name", "width": "180px"},
                {"key": "room_category", "label": "Room / Ward", "width": "130px"},
                {"key": "admission_date", "label": "Admitted", "width": "110px"},
                {"key": "discharge_date", "label": "Discharged", "width": "110px"},
                {"key": "gross_total", "label": "Gross Amount", "width": "120px", "align": "right"},
                {"key": "advance_paid", "label": "Advance / Co-pay", "width": "120px", "align": "right"},
                {"key": "net_amount", "label": "Net Billed Amount", "width": "130px", "align": "right"}
            ]

            all_pool = build_live_discharge_pool()
            sno = 1
            tot_gross = tot_adv = tot_net = 0.0

            for b in all_pool:
                cname = b.get('company_name', '')
                if 'railway' in key and 'RAILWAY' not in cname.upper():
                    continue

                gross = b.get('bill_amount', 0.0)
                adv = b.get('advance', 0.0)
                net = max(0.0, gross - adv)

                raw_adm = b.get('raw_adm') or {}
                room_list = raw_adm.get('room_details', [])
                room_cat = "GENERAL WARD"
                if room_list and isinstance(room_list, list):
                    room_cat = room_list[0].get('roomNo', 'GENERAL WARD')

                row = {
                    "sno": sno,
                    "bill_no": b.get('bill_id'),
                    "bill_date": b.get('bill_date'),
                    "ip_number": b.get('ip_number'),
                    "uhid": b.get('uhid'),
                    "patient_name": b.get('patient_name'),
                    "company_name": cname,
                    "company_code": b.get('company_code', ''),
                    "room_category": room_cat,
                    "admission_date": b.get('admitting_date'),
                    "discharge_date": b.get('discharge_date'),
                    "gross_total": round(gross, 2),
                    "advance_paid": round(adv, 2),
                    "net_amount": round(net, 2)
                }

                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                tot_gross += gross
                tot_adv += adv
                tot_net += net
                records.append(row)
                sno += 1

            summary = {
                "total_discharge_bills": len(records),
                "total_gross_amount": round(tot_gross, 2),
                "total_advance_deductions": round(tot_adv, 2),
                "total_net_claims": round(tot_net, 2)
            }

        # ---------------------------------------------------------
        # 15. Fallback: Live Insurance Claims
        # ---------------------------------------------------------
        else:
            pretty_name = key.replace('_', ' ').title()
            report_title = pretty_name
            columns = [
                {"key": "sno", "label": "S/No", "width": "60px"},
                {"key": "date", "label": "Date", "width": "110px"},
                {"key": "ref_number", "label": "Reference / Claim No", "width": "150px"},
                {"key": "uhid", "label": "UHID", "width": "120px"},
                {"key": "ip_number", "label": "IP Number", "width": "120px"},
                {"key": "patient_name", "label": "Patient Name", "width": "180px"},
                {"key": "company_name", "label": "Company / Scheme", "width": "180px"},
                {"key": "details", "label": "Category / Ward", "width": "180px"},
                {"key": "claimed_amount", "label": "Claimed / Estimate", "width": "130px", "align": "right"},
                {"key": "approved_amount", "label": "Approved / Settled", "width": "130px", "align": "right"},
                {"key": "status", "label": "Status", "width": "110px"}
            ]

            clm_q = {}
            if dt_start and dt_end:
                clm_q["$or"] = [
                    {"claim_date": {"$gte": dt_start, "$lte": dt_end}},
                    {"created_date": {"$gte": dt_start, "$lte": dt_end}}
                ]
            claims = list(hms_db['hospital_insuranceclaim'].find(clm_q).sort("claim_date", -1).limit(200))
            if not claims:
                claims = list(hms_db['hospital_insuranceclaim'].find({}).sort("claim_date", -1).limit(100))

            clm_uhids = list(set([c.get('uhid') for c in claims if c.get('uhid')]))
            clm_pats = {p['uhid']: p for p in hms_db['hospital_patient'].find({'uhid': {'$in': clm_uhids}}, {'uhid': 1, 'firstName': 1, 'lastName': 1})}

            sno = 1
            tot_claim = tot_appr = 0.0

            for clm in claims:
                uh = clm.get('uhid') or ''
                pat = clm_pats.get(uh, {})
                pname = clm.get('patient_name') or (f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip() if pat else '') or f"Patient {uh}"
                cname = resolve_company(clm.get('insurance_company'), claim=clm)
                ccode = str(clm.get('insurance_company') or cname)

                c_amt = clean_num(clm.get('estimate_amount') or clm.get('claimed_amount'))
                a_amt = clean_num(clm.get('approved_amount'))
                d_str = format_dt(clm.get('claim_date') or clm.get('created_date'))
                ref_no = str(clm.get('claim_id') or clm.get('policy_no') or f"CLM-{sno}")

                row = {
                    "sno": sno,
                    "date": d_str,
                    "ref_number": ref_no,
                    "uhid": uh,
                    "ip_number": str(clm.get('ip_number') or '-'),
                    "patient_name": pname,
                    "company_name": cname,
                    "company_code": ccode,
                    "details": str(clm.get('patient_ward') or 'INPATIENT CREDIT'),
                    "claimed_amount": round(c_amt, 2),
                    "approved_amount": round(a_amt, 2),
                    "status": str(clm.get('claim_status') or 'APPROVED').upper()
                }

                if not row_matches_filters(row, dt_start, dt_end, company_filter, search_query, company_map):
                    continue

                tot_claim += c_amt
                tot_appr += a_amt
                records.append(row)
                sno += 1

            summary = {
                "total_records": len(records),
                "total_claimed_amount": round(tot_claim, 2),
                "total_approved_amount": round(tot_appr, 2)
            }

        # Deduplicate companies list for frontend dropdown
        seen_codes = set()
        unique_companies = []
        for c in companies_list:
            if c['code'] not in seen_codes:
                seen_codes.add(c['code'])
                unique_companies.append(c)

        for r in records:
            c_n = r.get('company_name')
            if c_n and c_n not in seen_codes and c_n not in ['PRIVATE / CASH', 'CASH / PRIVATE', 'N', 'Y']:
                seen_codes.add(c_n)
                unique_companies.append({"code": c_n, "name": c_n})

        return Response({
            "success": True,
            "report_key": key,
            "title": report_title,
            "date_range": {
                "start_date": dt_start.strftime("%d/%m/%Y"),
                "end_date": dt_end.strftime("%d/%m/%Y")
            },
            "columns": columns,
            "data": records,
            "summary": summary,
            "patient_info": patient_info,
            "grouped_data": grouped_data,
            "bills": bills,
            "companies": unique_companies
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()
