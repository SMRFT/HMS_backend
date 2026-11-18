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

# IST bounds for 15/11/2026:
# 2026-11-15 00:00:00 IST = 2026-11-14 18:30:00 UTC
# 2026-11-15 23:59:59 IST = 2026-11-15 18:29:59 UTC
start_utc = datetime(2026, 11, 14, 18, 30, 0)
end_utc = datetime(2026, 11, 15, 18, 29, 59, 999999)

docs_ist_bounds = list(col.find({
    'created_date': {'$gte': start_utc, '$lte': end_utc},
    '$or': [{'outlet_code': 'OLET003'}, {'outlet': 'OLET003'}]
}))
print(f"Docs with proper IST bounds for OLET003: {len(docs_ist_bounds)}")

docs_by_shift = list(col.find({'shift_no': {'$in': shifts_003}}))
print(f"Docs in the 7 shifts of OLET003: {len(docs_by_shift)}")

shift_bill_nos = set(str(d.get('bill_no') or d.get('bill_number')) for d in docs_by_shift)
ist_bill_nos = set(str(d.get('bill_no') or d.get('bill_number')) for d in docs_ist_bounds)

print("In shift but not in IST bounds:", shift_bill_nos - ist_bill_nos)
print("In IST bounds but not in shift:", ist_bill_nos - shift_bill_nos)

# Let's sum amounts
tot_shift_amt = sum(float(str(d.get('collected_amount') or 0)) for d in docs_by_shift)
tot_ist_amt = sum(float(str(d.get('collected_amount') or 0)) for d in docs_ist_bounds)
print(f"Total Shift Docs Amt: {tot_shift_amt:.2f}")
print(f"Total IST Docs Amt: {tot_ist_amt:.2f}")

