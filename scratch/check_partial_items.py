import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

# Find ward requests with status Processing or Billed that have some items not yet dispatched
docs = list(db['hospital_pharmacybilling'].find({
    'is_ward_request': True,
    'billing_status': {'$in': ['Processing', 'Billed']}
}).sort('Bill_id', -1).limit(5))

for d in docs:
    print(f"\nBill_id: {d.get('Bill_id')} | status: {d.get('billing_status')} | stored_total: {d.get('total_amount')}")
    for idx, m in enumerate(d.get('medicine_particulars', [])):
        print(f"  Item {idx+1}: id={m.get('item_id')} | qty={m.get('qty')} | disp={m.get('dispatched_qty')} | price={m.get('price')} | mrp={m.get('mrp')} | tot={m.get('total')} | is_del={m.get('is_deleted')}")
