import os, time
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
uri = os.getenv('GLOBAL_DB_HOST')
print('URI:', uri)

t0 = time.time()
client = MongoClient(uri, serverSelectionTimeoutMS=5000)
global_db = client['Global']
hms_db = client['HMS']

t1 = time.time()
dept_cnt = global_db['backend_diagnostics_Departments'].count_documents({})
print(f'Departments: {dept_cnt} in {time.time()-t1:.2f}s')

t2 = time.time()
desig_cnt = global_db['backend_diagnostics_Designation'].count_documents({})
print(f'Designations: {desig_cnt} in {time.time()-t2:.2f}s')

t3 = time.time()
profiles = list(global_db['backend_diagnostics_profile'].find({'isDoctor': True}))
print(f'Doctor profiles: {len(profiles)} in {time.time()-t3:.2f}s')

t4 = time.time()
user_cnt = global_db['backend_diagnostics_user'].count_documents({})
print(f'Users: {user_cnt} in {time.time()-t4:.2f}s')

t5 = time.time()
hosp_doc_cnt = hms_db['hospital_doctor'].count_documents({})
print(f'Hospital doctors: {hosp_doc_cnt} in {time.time()-t5:.2f}s')
