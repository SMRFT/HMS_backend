import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

cursor = db['hospital_pharmacybilling'].find({
    '$or': [
        {'is_cancelled': True},
        {'status': 'Cancelled'},
        {'status': 'cancelled'}
    ]
})

mismatched = []
for d in cursor:
    b_st = d.get('billing_status')
    if b_st != 'Cancelled':
        mismatched.append({
            'Bill_id': d.get('Bill_id'),
            'request_no': d.get('request_no'),
            'bill_no': d.get('bill_no'),
            'status': d.get('status'),
            'billing_status': b_st,
            'is_cancelled': d.get('is_cancelled')
        })

print(f'Total cancelled docs with billing_status != Cancelled: {len(mismatched)}')
for m in mismatched:
    print(m)
