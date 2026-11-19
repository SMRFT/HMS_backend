import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
mongo_uri = os.getenv('GLOBAL_DB_HOST')
db = MongoClient(mongo_uri)['HMS']

# 1. Update billed MRIP093 (Bill_id: 23337) with official pharmacy bill number 262701037225
res1 = db['hospital_pharmacybilling'].update_one(
    {'Bill_id': 23337},
    {'$set': {
        'bill_no': '262701037225',
        'billed_bill_no': '262701037225',
        'converted_bill_no': '262701037225',
        'dispatch_history.0.bill_no': '262701037225',
        'request_no': 'MRIP093'
    }}
)
print('Updated Bill_id 23337:', res1.modified_count)

# 2. For active pending ward requests, ensure request_no is set and bill_no is None
pending_list = [23369, 23370, 23372]
for bid in pending_list:
    doc = db['hospital_pharmacybilling'].find_one({'Bill_id': bid})
    if doc:
        req_num = doc.get('request_no') or doc.get('bill_no')
        res = db['hospital_pharmacybilling'].update_one(
            {'Bill_id': bid},
            {'$set': {
                'request_no': req_num,
                'bill_no': None
            }}
        )
        print(f'Updated Bill_id {bid}: request_no={req_num}, bill_no=None')
