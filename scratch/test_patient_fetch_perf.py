import os, time, sys
from dotenv import load_dotenv
from pymongo import MongoClient
import pytz
from datetime import datetime

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

ist = pytz.timezone('Asia/Kolkata')
s = ist.localize(datetime(2026, 11, 15, 0, 0, 0))
e = ist.localize(datetime(2026, 11, 20, 23, 59, 59))

t0 = time.time()
bills = list(db['hospital_billing'].find({'billed_date': {'$gte': s, '$lte': e}}, {'patient_id': 1, 'uhid': 1}))
print(f'Fetched {len(bills)} bills in {time.time()-t0:.2f}s', flush=True)

uhids = list(set([str(b.get('uhid')).strip() for b in bills if b.get('uhid')]))
patient_ids = [b.get('patient_id') for b in bills if b.get('patient_id') is not None]
int_patient_ids = list(set([int(pid) for pid in patient_ids if isinstance(pid, int) or (isinstance(pid, str) and pid.isdigit())]))

print(f'UHIDs: {len(uhids)}, Int IDs: {len(int_patient_ids)}', flush=True)

# Test 1: Query by UHID only
t0 = time.time()
res_uhid = list(db['hospital_patient'].find({'uhid': {'$in': uhids}}, {'uhid': 1, 'id': 1, 'created_date': 1}))
print(f'Query by UHID only: {len(res_uhid)} docs in {time.time()-t0:.2f}s', flush=True)

# Test 2: Query by id only
t0 = time.time()
res_id = list(db['hospital_patient'].find({'id': {'$in': int_patient_ids}}, {'uhid': 1, 'id': 1, 'created_date': 1}))
print(f'Query by ID only: {len(res_id)} docs in {time.time()-t0:.2f}s', flush=True)
