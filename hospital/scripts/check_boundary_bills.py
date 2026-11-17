import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os
from dotenv import load_dotenv
load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env')
from pymongo import MongoClient
from datetime import datetime

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

col = db['hospital_cashcountercollection']

# Early morning 15/11/2026 IST = 2026-11-14 18:30:00 to 2026-11-15 00:00:00 UTC
early_docs = list(col.find({
    'created_date': {'$gte': datetime(2026, 11, 14, 18, 30), '$lt': datetime(2026, 11, 15, 0, 0)}
}))

print(f"Bills between 00:00 and 05:30 AM IST on 15/11/2026 (stored on 14/11 UTC): {len(early_docs)}")
for d in early_docs:
    print(f"Bill {d.get('bill_no') or d.get('bill_number')}: outlet={d.get('outlet_code') or d.get('outlet')}, shift={d.get('shift_no')}, amt={d.get('collected_amount')}, cat={d.get('billing_category')}, utc={d.get('created_date')}")

# Early morning 16/11/2026 IST = 2026-11-15 18:30:00 to 2026-11-16 00:00:00 UTC
late_docs = list(col.find({
    'created_date': {'$gte': datetime(2026, 11, 15, 18, 30), '$lt': datetime(2026, 11, 16, 0, 0)}
}))
print(f"\nBills between 00:00 and 05:30 AM IST on 16/11/2026 (stored on 15/11 UTC): {len(late_docs)}")
for d in late_docs:
    print(f"Bill {d.get('bill_no') or d.get('bill_number')}: outlet={d.get('outlet_code') or d.get('outlet')}, shift={d.get('shift_no')}, amt={d.get('collected_amount')}, cat={d.get('billing_category')}, utc={d.get('created_date')}")

