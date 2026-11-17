import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os
from dotenv import load_dotenv
load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env')
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

col = db['hospital_cashcountercollection']

# Find bills around 15/11/2026
bills = ['2627023284', '262733000004', '262738000002', '2627003028', '2627003029', '2627003031', '2627003032', '2627003033']
for b in bills:
    doc = col.find_one({'$or': [{'bill_no': b}, {'bill_number': b}]})
    if doc:
        print(f"Bill {b}: created_date={doc.get('created_date')} (type {type(doc.get('created_date'))}), shift={doc.get('shift_no')}, mode={doc.get('payment_mode')}, amt={doc.get('collected_amount')}, cat={doc.get('billing_category')}")
    else:
        print(f"Bill {b} NOT FOUND")

