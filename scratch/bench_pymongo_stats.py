import os
import time
from datetime import datetime, time as dtime
from dotenv import load_dotenv
from pymongo import MongoClient
import pytz

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

ist = pytz.timezone('Asia/Kolkata')
start_naive = datetime.combine(datetime.strptime('2026-11-21', '%Y-%m-%d').date(), dtime.min)
end_naive = datetime.combine(datetime.strptime('2026-11-21', '%Y-%m-%d').date(), dtime.max)
start_dt = ist.localize(start_naive)
end_dt = ist.localize(end_naive)

print('Testing direct PyMongo query...')
t0 = time.time()

# 1. Fetch bills for the date range
query = {
    'billed_date': {'$gte': start_dt, '$lte': end_dt}
}
# Also handle if billed_date is naive UTC or string
bills = list(db['hospital_billing'].find(query, {'patient_id': 1, 'uhid': 1, 'bill_number': 1, 'billed_date': 1}))
print(f'Fetched {len(bills)} bills in {time.time()-t0:.2f}s')

if not bills:
    # check date format in hospital_billing
    sample = list(db['hospital_billing'].find({}, {'billed_date': 1, 'bill_number': 1, 'patient_id': 1}).sort('billed_date', -1).limit(5))
    print('Sample billed_date in hospital_billing:')
    for s in sample:
        print(s.get('bill_number'), s.get('billed_date'), type(s.get('billed_date')), s.get('patient_id'))
