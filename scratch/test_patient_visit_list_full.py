import os, sys, time
from dotenv import load_dotenv

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
sys.path.insert(0, 'D:/Parthi/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')

import django
django.setup()

from pymongo import MongoClient
from django.utils import timezone
import pytz
from datetime import datetime, time as dtime

mongo_host = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(mongo_host, serverSelectionTimeoutMS=5000)
hms_db = client['HMS']
global_db = client['Global']

ist = pytz.timezone('Asia/Kolkata')
today = timezone.localdate()
start_dt = timezone.make_aware(datetime.combine(today, dtime.min))
end_dt = timezone.make_aware(datetime.combine(today, dtime.max))

t0 = time.time()
billing_coll = hms_db['hospital_billing']
patient_coll = hms_db['hospital_patient']
refund_coll = hms_db['hospital_refund']
diag_coll = global_db['backend_diagnostics_profile']

bills = list(billing_coll.find({'billed_date': {'$gte': start_dt, '$lte': end_dt}}).sort('billed_date', -1))
print(f'Bills today: {len(bills)}', flush=True)

patient_ids = []
uhids = []
all_emp_ids = set()
bill_numbers = []

for b in bills:
    pid = b.get('patient_id')
    if pid is not None:
        if isinstance(pid, int):
            patient_ids.append(pid)
        elif isinstance(pid, str) and pid.isdigit():
            patient_ids.append(int(pid))
    uh = b.get('uhid')
    if uh:
        uhids.append(str(uh).strip())
    
    if b.get('bill_number'):
        bill_numbers.append(b['bill_number'])
    if b.get('doctor_id'):
        all_emp_ids.add(str(b['doctor_id']).strip())
    if b.get('created_by'):
        all_emp_ids.add(str(b['created_by']).strip())
    for h in (b.get('edit_history') or []):
        if h.get('user'):
            all_emp_ids.add(str(h.get('user')).strip())
        changes = h.get('changes', {})
        if 'doctor' in changes and isinstance(changes['doctor'], dict):
            old_d = changes['doctor'].get('old')
            new_d = changes['doctor'].get('new')
            if old_d: all_emp_ids.add(str(old_d).strip())
            if new_d: all_emp_ids.add(str(new_d).strip())

# Fetch patients
patient_map = {}
pids_list = list(set(patient_ids))
uhs_list = list(set(uhids))
for i in range(0, len(pids_list), 100):
    chunk = pids_list[i:i+100]
    for p in patient_coll.find({'id': {'$in': chunk}}):
        if p.get('id') is not None:
            patient_map[p['id']] = p
            patient_map[str(p['id'])] = p
        if p.get('uhid'):
            patient_map[str(p['uhid']).strip()] = p

missing_uhs = [u for u in uhs_list if u not in patient_map]
for i in range(0, len(missing_uhs), 100):
    chunk = missing_uhs[i:i+100]
    for p in patient_coll.find({'uhid': {'$in': chunk}}):
        if p.get('id') is not None:
            patient_map[p['id']] = p
            patient_map[str(p['id'])] = p
        if p.get('uhid'):
            patient_map[str(p['uhid']).strip()] = p

# Fetch emp map
emp_map = {}
if all_emp_ids:
    for doc in diag_coll.find({"employeeId": {"$in": list(all_emp_ids)}}, {"employeeId": 1, "employeeName": 1}):
        if doc.get("employeeId") and doc.get("employeeName"):
            emp_map[str(doc.get("employeeId")).strip()] = doc.get("employeeName")

# Fetch refunds
refunds_by_bill = {}
if bill_numbers:
    for r in refund_coll.find({'bill_no': {'$in': bill_numbers}}):
        bno = r.get('bill_no')
        if bno:
            refunds_by_bill.setdefault(bno, []).append(r)

print(f'Fetched everything in {time.time()-t0:.3f}s: {len(patient_map)} patients, {len(emp_map)} emps, {len(refunds_by_bill)} refunds')
client.close()
