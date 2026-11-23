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
meds = b.get('medicine_particulars', [])

cum_total = sum(
    float(it.get("total") or it.get("calculated_price") or 0)
    for it in meds
    if not it.get("is_deleted") and not it.get("deleted_is")
)
print("cum_total of 26797 from DB items:", cum_total)
print("stored total_amount:", b.get('total_amount'))
