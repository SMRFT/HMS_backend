import os, time
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['Global']

print('Indexes on backend_diagnostics_user:', db['backend_diagnostics_user'].index_information(), flush=True)
print('Count of backend_diagnostics_user:', db['backend_diagnostics_user'].count_documents({}), flush=True)

# Sample document
sample = db['backend_diagnostics_user'].find_one({'is_active': True})
print('Sample user:', sample, flush=True)
