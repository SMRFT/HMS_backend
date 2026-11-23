import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from hospital.models import PharmacyBilling

sql_bill = PharmacyBilling.objects.filter(bill_no="262702041404").first()
print(f"SQL bill by bill_no 262702041404 found: {sql_bill is not None}")

sql_by_id = PharmacyBilling.objects.filter(Bill_id=23711).first()
if sql_by_id:
    print(f"SQL Bill_id 23711: bill_no={sql_by_id.bill_no}, uhid={sql_by_id.uhid}")

# Let's search SQL by net_amount=924
print("\nSearching SQL by net_amount=924:")
for b in PharmacyBilling.objects.filter(net_amount=924):
    print(f"SQL: Bill_id={b.Bill_id}, bill_no={b.bill_no}, uhid={b.uhid}, date={b.bill_date}")

# Let's search MongoDB by net_amount=924
from pymongo import MongoClient
client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
mongo_db = client["HMS"]
billing_col = mongo_db["hospital_pharmacybilling"]
print("\nSearching Mongo by net_amount=924:")
for b in billing_col.find({"net_amount": 924.0}):
    print(f"Mongo: Bill_id={b.get('Bill_id')}, bill_no={b.get('bill_no')}, uhid={b.get('uhid')}, date={b.get('bill_date')}")

# Also search Mongo by patient UHID S022/007150 across all dates
print("\nSearching Mongo for UHID S022/007150 with items:")
for b in billing_col.find({"uhid": "S022/007150"}):
    med_names = [m.get('item_name') or m.get('item_id') for m in b.get('medicine_particulars', [])]
    print(f"Mongo: Bill_id={b.get('Bill_id')}, bill_no={b.get('bill_no')}, total={b.get('total_amount')}, date={b.get('created_date')}, items={med_names}")
