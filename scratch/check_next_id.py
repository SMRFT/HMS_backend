import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from hospital.counter_service import get_next_sequence_value
from pymongo import MongoClient

c = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']
col = c['hospital_pharmacybilling']

# Check max Bill_id in col
max_doc = col.find_one(sort=[("Bill_id", -1)])
print("Max Bill_id in hospital_pharmacybilling:", max_doc.get("Bill_id") if max_doc else None)

# Also check counters
counter = c['counters'].find_one({"_id": "pharmacy_billing_bill_id"})
print("Current counter pharmacy_billing_bill_id:", counter)

# Check if 23711 is referenced anywhere else
print("Checking Bill_id in hospital_cashcountercollection for 262702041404:")
cc = c['hospital_cashcountercollection'].find_one({"bill_no": "262702041404"})
print("Cash counter collection doc Bill_id:", cc.get("Bill_id") if cc else None)
