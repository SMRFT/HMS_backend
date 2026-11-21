import os, sys, time, traceback
from dotenv import load_dotenv

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
sys.path.insert(0, 'D:/Parthi/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')

import django
django.setup()

from pymongo import MongoClient
from hospital.Views.doctormaster import get_department_mapping, get_designation_mapping, get_active_doctor_profiles

client = MongoClient(os.getenv('GLOBAL_DB_HOST'), serverSelectionTimeoutMS=5000)
global_db = client['Global']
hms_db = client['HMS']

t0 = time.time()
print('Step 1: Fetching department mapping...', flush=True)
dept_map = get_department_mapping(global_db)
print(f'Dept mapping done ({len(dept_map)}) in {time.time()-t0:.2f}s', flush=True)

t1 = time.time()
print('Step 2: Fetching designation mapping...', flush=True)
desig_map = get_designation_mapping(global_db)
print(f'Desig mapping done ({len(desig_map)}) in {time.time()-t1:.2f}s', flush=True)

t2 = time.time()
print('Step 3: Fetching active doctor profiles...', flush=True)
doctors = get_active_doctor_profiles(
    global_db,
    {
        "employeeName": 1,
        "department": 1,
        "specialty": 1,
        "designation": 1,
        "email": 1,
        "mobileNumber": 1,
    }
)
print(f'Active doctor profiles done ({len(doctors)}) in {time.time()-t2:.2f}s', flush=True)

t3 = time.time()
print('Step 4: Fetching doctor schedules from hospital_doctor...', flush=True)
doctor_collection = hms_db['hospital_doctor']
emp_ids = [doc.get('employeeId') for doc in doctors if doc.get('employeeId')]
print(f'emp_ids count: {len(emp_ids)}', flush=True)
schedules_map = {
    s.get("employeeId"): s
    for s in doctor_collection.find({"employeeId": {"$in": emp_ids}})
}
print(f'Schedules fetched ({len(schedules_map)}) in {time.time()-t3:.2f}s', flush=True)
client.close()
