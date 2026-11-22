import os
import sys
import time
from datetime import datetime, time as dtime
from dotenv import load_dotenv
from pymongo import MongoClient
import pytz

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

ist = pytz.timezone('Asia/Kolkata')
from_date = datetime.strptime('2026-11-21', '%Y-%m-%d').date()
to_date = datetime.strptime('2026-11-21', '%Y-%m-%d').date()

start_naive = datetime.combine(from_date, dtime.min)
end_naive = datetime.combine(to_date, dtime.max)
start_dt = ist.localize(start_naive)
end_dt = ist.localize(end_naive)

t0 = time.time()

# 1. Fetch bills directly from hospital_billing via PyMongo
bill_query = {
    'billed_date': {'$gte': start_dt, '$lte': end_dt}
}
doctor_id = None
if doctor_id:
    bill_query['doctor_id'] = str(doctor_id).strip()

bills = list(db['hospital_billing'].find(
    bill_query,
    {'patient_id': 1, 'uhid': 1, 'bill_number': 1, 'billed_date': 1}
))

total_visits = len(bills)
new_visit_count = 0
existing_visit_count = 0

# Collect patient identifiers
patient_ids = [b['patient_id'] for b in bills if b.get('patient_id')]
uhids = [b['uhid'] for b in bills if b.get('uhid')]

# 2. Batch fetch patients
patient_map = {}
if patient_ids or uhids:
    p_cursor = db['hospital_patient'].find(
        {'$or': [{'id': {'$in': patient_ids}}, {'uhid': {'$in': uhids}}]},
        {'id': 1, 'uhid': 1, 'created_date': 1}
    )
    for p in p_cursor:
        if p.get('id'):
            patient_map[p['id']] = p
        if p.get('uhid'):
            patient_map[str(p['uhid']).strip()] = p

for b in bills:
    p = patient_map.get(b.get('patient_id')) or patient_map.get(str(b.get('uhid') or '').strip())
    if not p:
        existing_visit_count += 1
        continue
    
    p_created = p.get('created_date')
    if not p_created:
        existing_visit_count += 1
        continue
    
    if hasattr(p_created, 'tzinfo') and p_created.tzinfo is None:
        p_created = ist.localize(p_created)
    elif not hasattr(p_created, 'tzinfo'):
        try:
            p_created = datetime.fromisoformat(str(p_created))
            if p_created.tzinfo is None:
                p_created = ist.localize(p_created)
        except Exception:
            existing_visit_count += 1
            continue
            
    if p_created >= start_dt:
        new_visit_count += 1
    else:
        existing_visit_count += 1

elapsed = time.time() - t0
print(f'PyMongo stats computed in {elapsed:.3f}s:')
print({
    "new_visit": new_visit_count,
    "existing_visit": existing_visit_count,
    "total_visit": total_visits
})
