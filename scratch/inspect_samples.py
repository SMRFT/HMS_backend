import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

def inspect_bill(bill_id):
    b = db['hospital_pharmacybilling'].find_one({'Bill_id': bill_id})
    print(f"\n=================== BILL {bill_id} ===================")
    print("bill_no:", b.get('bill_no'))
    print("status:", b.get('billing_status'))
    print("mode:", b.get('billing_mode'))
    print("is_ward_request:", b.get('is_ward_request'))
    print("request_no:", b.get('request_no'))
    print("total_amount in doc:", b.get('total_amount'))
    print("net_amount in doc:", b.get('net_amount'))
    print("discount_amount in doc:", b.get('discount_amount'))
    print("overall_discount_amount in doc:", b.get('overall_discount_amount'))
    print("overall_discount_value in doc:", b.get('overall_discount_value'))
    print("overall_discount_type in doc:", b.get('overall_discount_type'))
    meds = b.get('medicine_particulars', [])
    print(f"Total medicines: {len(meds)}")
    for idx, m in enumerate(meds[:5]):
        print(f"  Item {idx+1}: id={m.get('item_id')} | qty={m.get('qty')} | disp={m.get('dispatched_qty')} | mrp={m.get('mrp')} | price={m.get('price')} | calc_price={m.get('calculated_price')} | tot={m.get('total')} | del={m.get('is_deleted')}")
    if len(meds) > 5:
        print(f"  ... and {len(meds)-5} more items")

# Inspect Ward/MedicineChart bills
inspect_bill(26927) # Pending ward request
inspect_bill(26797) # Completed ward request
inspect_bill(26638) # Normal DIRECT
inspect_bill(26635) # Normal DIRECT
