import os, time
from dotenv import load_dotenv
from pymongo import MongoClient
import pytz
from datetime import datetime

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

ist = pytz.timezone('Asia/Kolkata')
s = ist.localize(datetime(2026, 11, 21, 0, 0, 0))
e = ist.localize(datetime(2026, 11, 21, 23, 59, 59, 999999))

t0 = time.time()
# 1. Fetch bills for the date range
bills = list(db['hospital_billing'].find(
    {'billed_date': {'$gte': s, '$lte': e}},
    {'patient_id': 1, 'uhid': 1, 'bill_number': 1}
))
total_visits = len(bills)

# 2. Fetch only new patients created >= s
# (Any patient created >= s is considered a 'new_visit')
new_patients = list(db['hospital_patient'].find(
    {'created_date': {'$gte': s}},
    {'id': 1, 'uhid': 1}
))

new_patient_ids = set()
new_uhids = set()
for p in new_patients:
    if p.get('id') is not None:
        new_patient_ids.add(p['id'])
        new_patient_ids.add(str(p['id']))
    if p.get('uhid'):
        new_uhids.add(str(p['uhid']).strip())

new_visit_count = 0
existing_visit_count = 0

for b in bills:
    pid = b.get('patient_id')
    uh = str(b.get('uhid') or '').strip()
    
    is_new = False
    if pid is not None and (pid in new_patient_ids or str(pid) in new_patient_ids):
        is_new = True
    elif uh and uh in new_uhids:
        is_new = True
        
    if is_new:
        new_visit_count += 1
    else:
        existing_visit_count += 1

elapsed = time.time() - t0
print(f'Computed in {elapsed:.3f}s:')
print({
    "new_visit": new_visit_count,
    "existing_visit": existing_visit_count,
    "total_visit": total_visits
})
