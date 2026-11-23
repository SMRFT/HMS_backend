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
for idx, m in enumerate(b.get('medicine_particulars', [])):
    print(f"Item {idx+1}: {m}")
