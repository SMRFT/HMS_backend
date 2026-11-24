from pymongo import MongoClient
import os
from dotenv import load_dotenv
load_dotenv('HMS_backend/.env', override=True)
c = MongoClient(os.getenv('GLOBAL_DB_HOST'))
col = c['HMS']['hospital_pharmacybilling']

conditions = [
    ('bill_no', {'bill_no': '262702041404'}),
    ('is_deleted', {'is_deleted': {'$ne': True}}),
    ('hospital_code', {'hospital_code': 'SH001'}),
    ('branch_code', {'branch_code': 'SHB001'}),
    ('payment_mode', {'payment_mode': {'$nin': ['Credit', 'credit']}}),
]

curr = {}
for name, cond in conditions:
    curr.update(cond)
    print(f'Matching up to {name}: {col.count_documents(curr)}')

doc = col.find_one(curr)
print('Final doc found:', bool(doc))
if doc:
    print('Doc details:', doc.get('bill_no'), doc.get('uhid'), doc.get('net_amount'), doc.get('doctor_name'))
