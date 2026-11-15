import sys, os, time, datetime
from dotenv import load_dotenv
load_dotenv('HMS_backend/.env')
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
hms_db = client['HMS']
global_db = client['Global']

oppharmacy_col = hms_db['hospital_pharmacybilling']
patient_col = hms_db['hospital_patient']
insurance_col = hms_db['hospital_insuranceprovider']
profile_col = global_db['backend_diagnostics_profile']
item_col = hms_db['hospital_pharmacyitem']
admission_col = hms_db['hospital_admission']
billtype_col = hms_db['hospital_billtype']

t_start = time.time()

# 1. Fetch bills
query = {
    'hospital_code': 'SH001',
    'branch_code': 'SHB001',
    'outlet_code': {'$in': ['OLET001', 'OLET002']},
    'billing_status': {'$in': ['Billed', 'Paid', 'Processing', 'deleted']}
}
bills = list(oppharmacy_col.find(query).sort('bill_date', -1).limit(200))
print(f'Fetched {len(bills)} bills in {time.time() - t_start:.3f}s')

# 2. Collect IDs
t0 = time.time()
uhids = set()
doc_ids = set()
emp_ids = set()
item_ids = set()

for b in bills:
    if b.get('uhid'): uhids.add(str(b['uhid']).strip())
    if b.get('doctor_id'): doc_ids.add(str(b['doctor_id']).strip())
    if b.get('billed_id'): emp_ids.add(str(b['billed_id']).strip())
    if b.get('created_by'): emp_ids.add(str(b['created_by']).strip())
    if b.get('cashier_id'): emp_ids.add(str(b['cashier_id']).strip())
    for it in (b.get('medicine_particulars') or []):
        if isinstance(it, dict) and it.get('item_id'):
            item_ids.add(it['item_id'])

# 3. Bulk Patients
patient_map = {}
patient_company_map = {}
patient_cust_type_map = {}
all_company_codes = set()

if uhids:
    for p in patient_col.find({'uhid': {'$in': list(uhids)}}, {'uhid': 1, 'firstName': 1, 'lastName': 1, 'salutation': 1, 'company_code': 1, 'customer_type': 1}):
        sal = (p.get('salutation') or '').strip()
        fn = (p.get('firstName') or '').strip()
        ln = (p.get('lastName') or '').strip()
        if ln.lower() == fn.lower(): ln = ''
        patient_map[p['uhid']] = ' '.join(f'{sal} {fn} {ln}'.split())
        cc = (p.get('company_code') or '').strip()
        if cc:
            patient_company_map[p['uhid']] = cc
            all_company_codes.add(cc)
        if p.get('customer_type'):
            patient_cust_type_map[p['uhid']] = p['customer_type']

# 4. Bulk Admissions
admission_map = {}
if uhids:
    for adm in admission_col.find({'uhid': {'$in': list(uhids)}}, {'uhid': 1, 'is_admitted': 1, 'customer_type': 1, 'company_code': 1, 'insurance_company': 1, 'room_details': 1, 'ipNumber': 1, 'inpatient_number': 1}).sort('created_date', -1):
        u = adm.get('uhid')
        if u not in admission_map or adm.get('is_admitted'):
            admission_map[u] = adm
        cc = (adm.get('company_code') or '').strip()
        if cc: all_company_codes.add(cc)

# 5. Bulk Insurance
insurance_map = {}
if all_company_codes:
    for ins in insurance_col.find({'company_code': {'$in': list(all_company_codes)}}, {'company_code': 1, 'company_name': 1}):
        cc = str(ins.get('company_code') or '').strip()
        insurance_map[cc] = ins.get('company_name', '')
        insurance_map[cc.upper()] = ins.get('company_name', '')

# 6. Bulk Profiles
all_pids = list(emp_ids | doc_ids)
profile_map = {}
if all_pids:
    search_q = []
    for pid in all_pids:
        search_q.append(pid)
        if pid.isdigit(): search_q.append(int(pid))
    for prof in profile_col.find({'employeeId': {'$in': search_q}}, {'employeeId': 1, 'employeeName': 1}):
        profile_map[str(prof.get('employeeId'))] = prof.get('employeeName', '')

# 7. Bulk Items
item_map = {}
if item_ids:
    q_iids = list(item_ids) + [str(x) for x in item_ids if not isinstance(x, str)] + [int(x) for x in item_ids if str(x).isdigit()]
    for itm in item_col.find({'item_id': {'$in': q_iids}}, {'item_id': 1, 'item_name': 1, 'hsn': 1, 'hsn_code': 1, 'CGST_Percentage': 1, 'SGST_Percentage': 1}):
        iid = itm.get('item_id')
        item_map[iid] = itm
        item_map[str(iid)] = itm

print(f'All bulk lookups done in {time.time() - t0:.3f}s')
print(f'TOTAL ELAPSED TIME: {time.time() - t_start:.3f}s')
