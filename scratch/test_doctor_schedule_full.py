import os, sys, time
from dotenv import load_dotenv

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
sys.path.insert(0, 'D:/Parthi/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')

import django
django.setup()

from pymongo import MongoClient
from hospital.Views.doctormaster import get_department_mapping, get_designation_mapping, convert_decimal128_to_float

t0 = time.time()
client = MongoClient(os.getenv('GLOBAL_DB_HOST'), serverSelectionTimeoutMS=5000)
global_db = client['Global']
hms_db = client['HMS']

dept_map = get_department_mapping(global_db)
desig_map = get_designation_mapping(global_db)

# New get_active_doctor_profiles logic:
profile_coll = global_db['backend_diagnostics_profile']
user_coll = global_db['backend_diagnostics_user']

profiles = list(profile_coll.find({"isDoctor": True}, {
    "employeeName": 1,
    "department": 1,
    "specialty": 1,
    "designation": 1,
    "email": 1,
    "mobileNumber": 1,
    "employeeId": 1,
    "_id": 0
}))

unique_profiles = []
seen_emp_ids = set()
for doc in profiles:
    eid = str(doc.get("employeeId") or "").strip()
    if not eid or eid in seen_emp_ids:
        continue
    seen_emp_ids.add(eid)
    unique_profiles.append(doc)

active_users = user_coll.find({"is_active": True}, {"employeeId": 1, "_id": 0})
active_emp_ids = set(str(u.get("employeeId") or "").strip() for u in active_users)

doctors = [
    doc for doc in unique_profiles
    if str(doc.get("employeeId") or "").strip() in active_emp_ids
]

# Schedules
doctor_coll = hms_db['hospital_doctor']
emp_ids = [doc.get('employeeId') for doc in doctors if doc.get('employeeId')]
schedules_map = {
    s.get("employeeId"): s
    for s in doctor_coll.find({"employeeId": {"$in": emp_ids}})
}

client.close()
elapsed = time.time() - t0
print(f'Full doctor_schedule_list pipeline completed in {elapsed:.3f}s!')
print(f'Total doctors: {len(doctors)}, Schedules matched: {len(schedules_map)}')
