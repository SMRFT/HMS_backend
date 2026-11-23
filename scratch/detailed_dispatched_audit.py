import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient
from datetime import datetime, timezone
from collections import defaultdict

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

start_today = datetime(2026, 11, 23, 0, 0, 0, tzinfo=timezone.utc)
end_today = datetime(2026, 11, 23, 23, 59, 59, tzinfo=timezone.utc)

today_bills = list(db['hospital_pharmacybilling'].find({
    'created_date': {'$gte': start_today, '$lte': end_today}
}).sort('Bill_id', 1))

total_count = len(today_bills)

missing_bills = []
present_bills = []

for b in today_bills:
    meds = b.get('medicine_particulars', [])
    missing_in_bill = [m for m in meds if m.get('dispatched_qty') is None]
    if missing_in_bill:
        missing_bills.append(b)
    else:
        present_bills.append(b)

print(f"Total bills today: {total_count}")
print(f"Bills with dispatched_qty on all items: {len(present_bills)}")
print(f"Bills with missing dispatched_qty on at least 1 item: {len(missing_bills)}")

# Categorize missing bills
by_status = defaultdict(int)
by_mode = defaultdict(int)
by_outlet = defaultdict(int)
by_combo = defaultdict(list)

for b in missing_bills:
    status = b.get('billing_status')
    mode = b.get('billing_mode')
    outlet = b.get('outlet_code')
    is_ward = b.get('is_ward_request')
    by_status[status] += 1
    by_mode[mode] += 1
    by_outlet[outlet] += 1
    combo_key = f"Outlet: {outlet} | Mode: {mode} | Status: {status} | is_ward: {is_ward}"
    by_combo[combo_key].append({
        'Bill_id': b.get('Bill_id'),
        'bill_no': b.get('bill_no'),
        'uhid': b.get('uhid'),
        'inpatient_number': b.get('inpatient_number'),
        'total_items': len(b.get('medicine_particulars', [])),
        'missing_items_count': sum(1 for m in b.get('medicine_particulars', []) if m.get('dispatched_qty') is None)
    })

print("\n--- Summary by Billing Status ---")
for s, c in sorted(by_status.items(), key=lambda x: -x[1]):
    print(f"  {s}: {c}")

print("\n--- Summary by Billing Mode ---")
for m, c in sorted(by_mode.items(), key=lambda x: -x[1]):
    print(f"  {m}: {c}")

print("\n--- Summary by Outlet ---")
for o, c in sorted(by_outlet.items(), key=lambda x: -x[1]):
    print(f"  {o}: {c}")

print("\n--- Detailed Breakdown by Category ---")
for combo, items in sorted(by_combo.items(), key=lambda x: -len(x[1])):
    print(f"\n{combo} (Count: {len(items)})")
    # Print first 5 bill IDs and numbers
    sample_bills = [f"Bill_id: {it['Bill_id']} (No: {it['bill_no']})" for it in items[:5]]
    print(f"  Sample bills: {', '.join(sample_bills)}")
    if len(items) > 5:
        print(f"  ... and {len(items)-5} more")

# Check specifically for IP CREDIT bills (like 26741)
ip_credit_missing = [b for b in missing_bills if b.get('billing_mode') == 'IP CREDIT']
print(f"\nTotal IP CREDIT bills missing dispatched_qty: {len(ip_credit_missing)}")

# Check specifically for DIRECT bills (OP Pharmacy cash/card)
direct_missing = [b for b in missing_bills if b.get('billing_mode') == 'DIRECT']
print(f"Total DIRECT bills missing dispatched_qty: {len(direct_missing)}")

# Check specifically for WARD REQUEST bills
ward_missing = [b for b in missing_bills if b.get('is_ward_request') == True or b.get('billing_mode') == 'WARD REQUEST']
print(f"Total WARD REQUEST bills missing dispatched_qty: {len(ward_missing)}")
for wb in ward_missing:
    print(f"  Ward Bill_id: {wb.get('Bill_id')}, bill_no: {wb.get('bill_no')}, status: {wb.get('billing_status')}, req_no: {wb.get('request_no')}")
