import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient
from datetime import datetime, timezone

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

start_today = datetime(2026, 11, 23, 0, 0, 0, tzinfo=timezone.utc)
end_today = datetime(2026, 11, 23, 23, 59, 59, tzinfo=timezone.utc)

today_bills = list(db['hospital_pharmacybilling'].find({'created_date': {'$gte': start_today, '$lte': end_today}}))

have_disp_modes = {}
missing_disp_modes = {}

for b in today_bills:
    meds = b.get('medicine_particulars', [])
    mode = b.get('billing_mode')
    status = b.get('billing_status')
    is_ward = b.get('is_ward_request')
    outlet = b.get('outlet_code')
    key = f'outlet={outlet} | mode={mode} | status={status} | is_ward={is_ward}'
    
    all_has = all(m.get('dispatched_qty') is not None for m in meds) if meds else False
    if all_has:
        have_disp_modes[key] = have_disp_modes.get(key, 0) + 1
    else:
        missing_disp_modes[key] = missing_disp_modes.get(key, 0) + 1

print('=== Bills WITH dispatched_qty ===')
for k, v in have_disp_modes.items():
    print(f'  {k}: {v}')

print('\n=== Bills MISSING dispatched_qty ===')
for k, v in missing_disp_modes.items():
    print(f'  {k}: {v}')

# Sample one bill from missing that has status Billed / IP CREDIT
sample_missing = next((b for b in today_bills if b.get('billing_mode') == 'IP CREDIT' and not all(m.get('dispatched_qty') is not None for m in b.get('medicine_particulars', []))), None)
if sample_missing:
    print(f"\nSample IP CREDIT missing dispatched_qty: Bill_id={sample_missing.get('Bill_id')}, bill_no={sample_missing.get('bill_no')}")
    print("Keys in bill:", list(sample_missing.keys()))
    print("First med keys:", list(sample_missing['medicine_particulars'][0].keys()))

# Sample one bill that HAS dispatched_qty
sample_has = next((b for b in today_bills if all(m.get('dispatched_qty') is not None for m in b.get('medicine_particulars', []))), None)
if sample_has:
    print(f"\nSample bill WITH dispatched_qty: Bill_id={sample_has.get('Bill_id')}, bill_no={sample_has.get('bill_no')}")
    print("Keys in bill:", list(sample_has.keys()))
    print("First med keys:", list(sample_has['medicine_particulars'][0].keys()))
