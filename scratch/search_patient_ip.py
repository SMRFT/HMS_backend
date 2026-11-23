import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

ip_no = "S026/008394"

print(f"=== Searching for inpatient_number '{ip_no}' across all collections ===")
for col_name in sorted(db.list_collection_names()):
    col = db[col_name]
    count = col.count_documents({'$or': [
        {'inpatient_number': ip_no},
        {'inpatient_no': ip_no},
        {'inpatientNo': ip_no},
        {'ip_number': ip_no},
        {'ipNumber': ip_no}
    ]})
    if count > 0:
        print(f"\nCollection '{col_name}': {count} documents")
        for doc in col.find({'$or': [
            {'inpatient_number': ip_no},
            {'inpatient_no': ip_no},
            {'inpatientNo': ip_no},
            {'ip_number': ip_no},
            {'ipNumber': ip_no}
        ]}):
            clean_d = {}
            for k, v in doc.items():
                if k in ['medicine_particulars', 'particulars', 'items', 'room_details']:
                    clean_d[k] = f"[{len(v)} items]" if isinstance(v, list) else str(v)
                else:
                    clean_d[k] = str(v)
            print(" ", clean_d)
