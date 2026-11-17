import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os
from dotenv import load_dotenv
load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env')
from pymongo import MongoClient
from datetime import datetime, date
import pytz

ist = pytz.timezone('Asia/Kolkata')
client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

col = db['hospital_cashcountercollection']

# Shifts of OLET003 on 15/11/2026
shifts_003 = [
    '2627/01/000006', '2627/01/000007', '2627/01/000008',
    '2627/01/000009', '2627/01/000010', '2627/01/000011', '2627/01/000012'
]

# Query by shift
docs_by_shift = list(col.find({'shift_no': {'$in': shifts_003}}))
print(f"Docs by shift ({len(shifts_003)} shifts): {len(docs_by_shift)}")

# Query by date (as currently done in date_wise_collection_summary)
f_d = date(2026, 11, 15)
t_d = date(2026, 11, 15)
f_dt = datetime.combine(f_d, datetime.min.time())
t_dt = datetime.combine(t_d, datetime.max.time())
docs_by_date = list(col.find({
    'created_date': {'$gte': f_dt, '$lte': t_dt},
    '$or': [{'outlet_code': 'OLET003'}, {'outlet': 'OLET003'}]
}))
print(f"Docs by naive date query for OLET003: {len(docs_by_date)}")

# Also let's check without outlet filter
docs_by_date_all = list(col.find({
    'created_date': {'$gte': f_dt, '$lte': t_dt}
}))
print(f"Docs by naive date query (ALL outlets): {len(docs_by_date_all)}")

# Let's inspect the difference
shift_bill_nos = set(str(d.get('bill_no') or d.get('bill_number')) for d in docs_by_shift)
date_bill_nos = set(str(d.get('bill_no') or d.get('bill_number')) for d in docs_by_date_all)

in_shift_not_date = shift_bill_nos - date_bill_nos
in_date_not_shift = date_bill_nos - shift_bill_nos

print("\nBills in shift but NOT in date query:")
for b in in_shift_not_date:
    d = next(x for x in docs_by_shift if str(x.get('bill_no') or x.get('bill_number')) == b)
    print(f"  Bill {b}: amt={d.get('collected_amount')}, shift={d.get('shift_no')}, created_date={d.get('created_date')}, cat={d.get('billing_category')}")

print("\nBills in date query but NOT in OLET003 shifts:")
for b in in_date_not_shift:
    d = next(x for x in docs_by_date_all if str(x.get('bill_no') or x.get('bill_number')) == b)
    print(f"  Bill {b}: amt={d.get('collected_amount')}, shift={d.get('shift_no')}, created_date={d.get('created_date')}, outlet={d.get('outlet_code') or d.get('outlet')}, cat={d.get('billing_category')}")

