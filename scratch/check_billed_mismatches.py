import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

since_date = datetime.now(timezone.utc) - timedelta(days=7)
cursor = db['hospital_pharmacybilling'].find({
    'created_date': {'$gte': since_date},
    'billing_status': {'$in': ['Billed', 'Paid', 'Completed']}
}).sort('Bill_id', -1)

bills = list(cursor)
print(f"Total BILLED/PAID/COMPLETED bills in last 7 days: {len(bills)}")

mismatches = []

for b in bills:
    b_id = b.get('Bill_id')
    b_no = b.get('bill_no')
    status = b.get('billing_status')
    mode = b.get('billing_mode')
    is_ward = b.get('is_ward_request')
    req_no = b.get('request_no')
    stored_total = float(b.get('total_amount') or 0.0)
    stored_net = float(b.get('net_amount') or 0.0)
    disc_amount = float(b.get('discount_amount') or b.get('total_item_discount') or b.get('overall_discount_amount') or 0.0)
    
    meds = [m for m in b.get('medicine_particulars', []) if not m.get('is_deleted') and not m.get('deleted_is')]
    if not meds:
        continue
        
    calc_sum_total = sum(float(m.get('total') or 0.0) for m in meds)
    calc_gross = sum(float(m.get('calculated_price') or (float(m.get('price') or m.get('mrp') or 0.0) * float(m.get('qty') or 0.0))) for m in meds)
    
    # In normal billing: stored_total is Gross, stored_net is Gross - Discount.
    # Check if stored_total matches gross AND stored_net matches calc_sum_total
    diff_gross = abs(stored_total - calc_gross)
    diff_net = abs(stored_net - round(calc_sum_total))
    
    # If neither gross nor net matches
    if diff_net > 1.0 and abs(stored_total - calc_sum_total) > 1.0:
        mismatches.append({
            'Bill_id': b_id,
            'bill_no': b_no,
            'status': status,
            'mode': mode,
            'is_ward': is_ward,
            'req_no': req_no,
            'stored_total': stored_total,
            'stored_net': stored_net,
            'calc_gross': round(calc_gross, 2),
            'calc_sum_total': round(calc_sum_total, 2),
            'disc_amount': disc_amount,
            'created_date': str(b.get('created_date'))[:16]
        })

print(f"Actual mismatched BILLED bills: {len(mismatches)} out of {len(bills)}")
print("\n--- Details of mismatched BILLED bills ---")
for m in mismatches[:20]:
    print(f"Bill_id: {m['Bill_id']} (No: {m['bill_no']}, Req: {m['req_no']}, Mode: {m['mode']}): stored_tot={m['stored_total']}, stored_net={m['stored_net']} vs calc_gross={m['calc_gross']}, calc_net={m['calc_sum_total']} | Date: {m['created_date']}")
if len(mismatches) > 20:
    print(f"... and {len(mismatches) - 20} more")
