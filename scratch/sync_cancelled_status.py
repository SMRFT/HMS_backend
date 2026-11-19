import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

# Synchronize billing_status for records where is_cancelled is True or status is Cancelled
res = db['hospital_pharmacybilling'].update_many(
    {
        '$or': [{'is_cancelled': True}, {'status': 'Cancelled'}],
        'billing_status': {'$ne': 'Cancelled'}
    },
    {
        '$set': {'billing_status': 'Cancelled'}
    }
)
print('Synchronized records count:', res.modified_count)

# Verify MRIP128
doc = db['hospital_pharmacybilling'].find_one({'Bill_id': 23380})
print('MRIP128 now:')
print('  status:', doc.get('status'))
print('  billing_status:', doc.get('billing_status'))
print('  is_cancelled:', doc.get('is_cancelled'))
