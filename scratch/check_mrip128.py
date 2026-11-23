import os, sys, django
sys.path.insert(0, r'D:\Parthi\HMS\HMS_backend')
from dotenv import load_dotenv
load_dotenv(r'D:\Parthi\HMS\HMS_backend\.env', override=True)
env = os.getenv('ENV_CLASSIFICATION', 'test')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', f'shanmugahospital_backend.settings-{env}' if env in ['prod', 'test'] else 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient

db_name = settings.DATABASES['default']['NAME']
client_host = settings.DATABASES['default'].get('CLIENT', {}).get('host')
client = MongoClient(client_host)
db = client[db_name]

# Check across all collections for MRIP128
for cname in db.list_collection_names():
    try:
        docs = list(db[cname].find({'$or': [{'request_no': 'MRIP128'}, {'bill_no': 'MRIP128'}, {'mrip_no': 'MRIP128'}, {'mripNo': 'MRIP128'}]}))
        if docs:
            print(f'=== Collection {cname}: {len(docs)} docs ===')
            for d in docs:
                print({k: d[k] for k in ['_id', 'request_no', 'bill_no', 'status', 'billing_status', 'is_cancelled', 'uhid', 'inpatient_number', 'created_date'] if k in d})
    except Exception as e:
        pass
