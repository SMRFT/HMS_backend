import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient
from hospital.models import PharmacyBilling

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

bill = db['hospital_pharmacybilling'].find_one({'Bill_id': 26797})
meds = [m for m in bill.get('medicine_particulars', []) if not m.get('is_deleted') and not m.get('deleted_is')]

calc_total = round(sum(float(m.get('total') or 0) for m in meds), 2)
rounded_net = float(round(calc_total))
round_off = round(rounded_net - calc_total, 2)

print(f"Fixing Bill 26797: total_amount={calc_total}, net_amount={rounded_net}, round_off={round_off}")

db['hospital_pharmacybilling'].update_one(
    {'_id': bill['_id']},
    {
        '$set': {
            'total_amount': calc_total,
            'net_amount': rounded_net,
            'round_off': round_off
        }
    }
)
PharmacyBilling.objects.filter(Bill_id=26797).update(
    total_amount=calc_total,
    net_amount=rounded_net
)
print("Updated Bill 26797 successfully.")
