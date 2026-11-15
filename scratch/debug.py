
from dotenv import load_dotenv; load_dotenv('HMS_backend/.env')
import os; from pymongo import MongoClient
col = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']['hospital_pharmacybilling']
for doc in col.find():
    if doc.get('billing_status'):
        print('doc:', doc.get('bill_no'), doc.get('outlet_code'), doc.get('billing_status'), doc.get('hospital_code'), doc.get('branch_code'))
