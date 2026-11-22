import os, sys, time
from dotenv import load_dotenv
from pymongo import MongoClient
import pytz
from datetime import datetime

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

ist = pytz.timezone('Asia/Kolkata')
s = ist.localize(datetime(2026, 11, 15, 0, 0, 0))
e = ist.localize(datetime(2026, 11, 20, 23, 59, 59, 999999))

t0 = time.time()
bills = list(db['hospital_billing'].find(
    {'billed_date': {'$gte': s, '$lte': e}}
).sort('billed_date', -1))
print(f'Fetched {len(bills)} bills in {time.time()-t0:.2f}s', flush=True)

patient_ids = []
uhids = []
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

t1 = time.time()
patient_map = {}
pids_list = list(set(patient_ids))
uhs_list = list(set(uhids))

for i in range(0, len(pids_list), 100):
    chunk = pids_list[i:i+100]
    for p in db['hospital_patient'].find({'id': {'$in': chunk}}):
        if p.get('id') is not None:
            patient_map[p['id']] = p
            patient_map[str(p['id'])] = p
        if p.get('uhid'):
            patient_map[str(p['uhid']).strip()] = p

missing_uhs = [u for u in uhs_list if u not in patient_map]
for i in range(0, len(missing_uhs), 100):
    chunk = missing_uhs[i:i+100]
    for p in db['hospital_patient'].find({'uhid': {'$in': chunk}}):
        if p.get('id') is not None:
            patient_map[p['id']] = p
            patient_map[str(p['id'])] = p
        if p.get('uhid'):
            patient_map[str(p['uhid']).strip()] = p

print(f'Fetched {len(patient_map)} patients for 893 bills in {time.time()-t1:.2f}s!', flush=True)
print(f'Total time: {time.time()-t0:.2f}s', flush=True)
