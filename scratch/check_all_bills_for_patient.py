import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

ip_no = "S026/008394"

bills = list(db['hospital_pharmacybilling'].find({'inpatient_number': ip_no}))
print(f"Total bills in hospital_pharmacybilling for {ip_no}: {len(bills)}")

for b in bills:
    b_id = b.get('Bill_id')
    b_no = b.get('bill_no')
    status = b.get('billing_status')
    mode = b.get('billing_mode')
    stored_total = float(b.get('total_amount') or 0.0)
    stored_net = float(b.get('net_amount') or 0.0)
    
    meds = b.get('medicine_particulars', [])
    calc_sum = sum(float(m.get('total') or 0.0) for m in meds if not m.get('is_deleted') and not m.get('deleted_is'))
    calc_gross = sum(float(m.get('calculated_price') or 0.0) for m in meds if not m.get('is_deleted') and not m.get('deleted_is'))
    
    diff = abs(stored_total - calc_sum)
    match_status = "OK" if diff < 0.5 else "MISMATCH!"
    print(f"Bill_id: {b_id} | bill_no: {b_no} | status: {status} | mode: {mode} | stored_tot: {stored_total:.2f} | calc_tot: {calc_sum:.2f} | {match_status}")
