import os, time
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['Global']

profile_collection = db['backend_diagnostics_profile']
user_collection = db['backend_diagnostics_user']

t0 = time.time()
profiles = list(profile_collection.find({"isDoctor": True}, {"employeeId": 1, "_id": 0}))
print(f'Profiles: {len(profiles)} in {time.time()-t0:.2f}s', flush=True)

query_eids = set()
for doc in profiles:
    eid = str(doc.get("employeeId") or "").strip()
    if eid:
        query_eids.add(eid)
        if eid.isdigit():
            query_eids.add(int(eid))

print(f'query_eids ({len(query_eids)}): {list(query_eids)[:10]}', flush=True)

t1 = time.time()
active_users = list(user_collection.find(
    {"employeeId": {"$in": list(query_eids)}, "is_active": True},
    {"employeeId": 1, "_id": 0}
))
print(f'Active users: {len(active_users)} in {time.time()-t1:.2f}s', flush=True)
