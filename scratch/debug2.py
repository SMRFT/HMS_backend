
from dotenv import load_dotenv; load_dotenv('HMS_backend/.env')
import os; from pymongo import MongoClient
col = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']['hospital_pharmacybilling']
q = {
    'hospital_code': 'SH001',
    'branch_code': 'SHB001',
    'outlet_code': {'': ['OLET001', 'OLET002']},
    'billing_status': {'': ['Billed', 'Paid', 'Processing', 'deleted']}
}
print('Without sort count:', col.count_documents(q))
print('With find and sort:', list(col.find(q).sort('bill_date', -1)))
