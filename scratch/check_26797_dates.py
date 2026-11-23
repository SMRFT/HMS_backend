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
if not b:
    b = db['hospital_pharmacybilling'].find_one({'bill_no': '262701038193'})

print('created_date:', b.get('created_date'))
print('lastmodified_date:', b.get('lastmodified_date'))
print('bill_date:', b.get('bill_date'))
print('billing_mode:', b.get('billing_mode'))
print('is_ward_request:', b.get('is_ward_request'))
print('request_no:', b.get('request_no'))
