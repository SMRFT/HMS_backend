import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

b = db['hospital_pharmacybilling'].find_one({'Bill_id': 26797})
print(f"=== BILL 26797 ===")
print("bill_no:", b.get('bill_no'))
print("request_no:", b.get('request_no'))
print("status:", b.get('billing_status'))
print("mode:", b.get('billing_mode'))
print("total_amount in doc:", b.get('total_amount'))
print("net_amount in doc:", b.get('net_amount'))

meds = b.get('medicine_particulars', [])
print(f"Total medicines: {len(meds)}")
sum_tot = 0
for idx, m in enumerate(meds):
    t = m.get('total')
    q = m.get('qty')
    disp = m.get('dispatched_qty')
    p = m.get('price')
    is_del = m.get('is_deleted')
    edit_hist = m.get('edit_history', [])
    print(f"  Item {idx+1}: id={m.get('item_id')} | qty={q} | disp={disp} | price={p} | total={t} | is_del={is_del} | edit_hist={len(edit_hist)}")
    if t is not None and not is_del:
        sum_tot += float(t)

print(f"Sum of active items total: {sum_tot}")
