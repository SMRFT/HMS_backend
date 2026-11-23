import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient
from bson import ObjectId

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

doc = db['hospital_salesreturn'].find_one({'_id': ObjectId('6b028e69c8f1b2c1fc4b20c4')})
if not doc:
    doc = db['hospital_salesreturn'].find_one({'return_bill_no': '262702000094'})

print("=== Found Sales Return Document ===")
for k, v in doc.items():
    print(f"  {k}: {v}")
