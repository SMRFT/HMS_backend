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

today_billed_wards = list(db['hospital_pharmacybilling'].find({
    'created_date': {'$gte': start_today, '$lte': end_today},
    'is_ward_request': True,
    'billing_status': {'$in': ['Billed', 'Completed']}
}))

print(f"Total Billed/Completed Ward Requests today: {len(today_billed_wards)}")

mismatches_today = []
for b in today_billed_wards:
    meds = b.get('medicine_particulars', [])
    active_meds = [m for m in meds if not m.get('is_deleted') and not m.get('deleted_is')]
    calc_sum = sum(float(m.get('total') or m.get('calculated_price') or 0) for m in active_meds)
    stored_tot = float(b.get('total_amount') or 0)
    
    if abs(calc_sum - stored_tot) > 1.0:
        mismatches_today.append({
            'Bill_id': b.get('Bill_id'),
            'bill_no': b.get('bill_no'),
            'req_no': b.get('request_no'),
            'stored_tot': stored_tot,
            'calc_sum': round(calc_sum, 2),
            'diff': round(abs(calc_sum - stored_tot), 2)
        })

print(f"Ward request bills today with mismatched total: {len(mismatches_today)}")
for m in mismatches_today:
    print(f"  Bill_id: {m['Bill_id']} (No: {m['bill_no']}, Req: {m['req_no']}): stored={m['stored_tot']} vs calc={m['calc_sum']} (diff={m['diff']})")
