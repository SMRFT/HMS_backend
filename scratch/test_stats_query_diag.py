import os
from dotenv import load_dotenv
from pymongo import MongoClient
import pytz
from datetime import datetime

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

ist = pytz.timezone('Asia/Kolkata')
s = ist.localize(datetime(2026, 11, 15, 0, 0, 0))
e = ist.localize(datetime(2026, 11, 20, 23, 59, 59))

cnt = db['hospital_billing'].count_documents({'billed_date': {'$gte': s, '$lte': e}})
print('Bill count 15 to 20:', cnt)

# If cnt > 0, let's see why patient fetch was slow
bills = list(db['hospital_billing'].find({'billed_date': {'$gte': s, '$lte': e}}, {'patient_id': 1, 'uhid': 1}))
print(f'Retrieved {len(bills)} bills')

uhids = list(set([str(b.get('uhid')).strip() for b in bills if b.get('uhid')]))
patient_ids = list(set([b.get('patient_id') for b in bills if b.get('patient_id') is not None]))
print(f'Unique UHIDs: {len(uhids)}, Unique patient_ids: {len(patient_ids)}')
