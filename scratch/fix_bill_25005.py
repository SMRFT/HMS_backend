import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient
from bson import ObjectId
from hospital.models import PharmacyBilling

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

bill_id = 25005
mongo_id = ObjectId('6aff0da86697998c1dc6d0ca')

bill = db['hospital_pharmacybilling'].find_one({'_id': mongo_id})
if not bill:
    print("Bill not found by _id, trying Bill_id")
    bill = db['hospital_pharmacybilling'].find_one({'Bill_id': bill_id})

meds = bill.get('medicine_particulars', [])
calc_gross = sum(float(m.get('calculated_price') or m.get('price', 0) * m.get('qty', 0) or 0) for m in meds if not m.get('is_deleted') and not m.get('deleted_is'))
calc_total = sum(float(m.get('total') or 0) for m in meds if not m.get('is_deleted') and not m.get('deleted_is'))
calc_gross = round(calc_gross, 2)
calc_total = round(calc_total, 2)
rounded_net = round(calc_total)
round_off = round(rounded_net - calc_total, 2)

print(f"Updating Bill 25005:")
print(f"  total_amount: {calc_total}")
print(f"  net_amount: {float(rounded_net)}")
print(f"  round_off: {round_off}")

# 1. Update MongoDB hospital_pharmacybilling
res = db['hospital_pharmacybilling'].update_one(
    {'_id': bill['_id']},
    {
        '$set': {
            'total_amount': calc_total,
            'net_amount': float(rounded_net),
            'round_off': round_off
        }
    }
)
print(f"MongoDB update result: matched={res.matched_count}, modified={res.modified_count}")

# 2. Update SQL PharmacyBilling
sql_updated = PharmacyBilling.objects.filter(Bill_id=bill_id).update(
    total_amount=calc_total,
    net_amount=float(rounded_net)
)
print(f"SQL PharmacyBilling rows updated: {sql_updated}")

# Verify MongoDB
updated_bill = db['hospital_pharmacybilling'].find_one({'_id': bill['_id']})
print("Verification from MongoDB:")
print(f"  Bill_id: {updated_bill.get('Bill_id')}")
print(f"  bill_no: {updated_bill.get('bill_no')}")
print(f"  inpatient_number: {updated_bill.get('inpatient_number')}")
print(f"  total_amount: {updated_bill.get('total_amount')}")
print(f"  net_amount: {updated_bill.get('net_amount')}")
print(f"  round_off: {updated_bill.get('round_off')}")
