import os, sys
from dotenv import load_dotenv
load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env')
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
sys.path.insert(0, 'd:/SMRFT/Projects/HMS/HMS_backend')
django.setup()
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

# Search for 780.05, 671.93, 2977.36, 907.28, 393.26 in hospital_pharmacybilling
for target in [780.05, 671.93, 2977.36, 907.28, 393.26]:
    docs = list(db.hospital_pharmacybilling.find({
        '$or': [
            {'net_amount': target},
            {'total_amount': target},
            {'taxable_amount': target}
        ]
    }))
    print(f"Target {target}: {len(docs)} docs")
    for d in docs:
        print(f"  Bill: {d.get('bill_no')}, UHID: {d.get('uhid')}, IP: {d.get('inpatient_number')}, Date: {d.get('bill_date')}")
